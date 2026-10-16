"""A simulated account for the cloud-proof harnesses: `--dry-run`, `rehearse` and the tests.

One in-memory world answers the public API (through CloudFront or the Gateway), S3 and SQS over
HTTP, and the AWS control plane (ECS, CloudWatch, Cost Explorer, logs, RDS, plus everything the
session code needs, delegated to the same `PlanTransport` the session CLI's own dry-run uses).
All time is virtual: `sleep` advances a clock, so a 45-minute window runs in milliseconds and a
test can ask for a slow encoder, a stuck requeue or a database that never pauses.

Nothing here proves anything about AWS. Every receipt written against this world is marked
simulated, its overall status is SIMULATED, and the summary writer refuses it.
"""

import contextlib
import io
import json
import time
import uuid
import zlib
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from scripts.aws.v1 import operations, release_cli
from scripts.aws.v1.deploy import DeployJournal
from scripts.aws.v1.proof import generator
from scripts.aws.v1.proof.context import Context, load_state
from scripts.aws.v1.proof.core import stamp
from scripts.aws.v1.transport import REGION

EPOCH = 1_792_233_600.0  # 2026-10-17T10:40:00Z, an arbitrary fixed wall-clock origin
ACCOUNT = "123456789012"
FRONTEND = "https://d111111abcdef8.cloudfront.net"
GATEWAY = "https://abc123def4.execute-api.ap-southeast-1.amazonaws.com"
S3_HOST = "dc2-sim-source.s3.ap-southeast-1.amazonaws.com"
OPEN_EDGE = {"ThrottlingBurstLimit": 10, "ThrottlingRateLimit": 5}
COOKIE = "session=sim-token; HttpOnly; Secure; SameSite=Strict; Path=/"


class VirtualClock:
    """Monotonic seconds that only move when something sleeps (or a request takes time)."""

    def __init__(self):
        self.t = time.monotonic() + 10_000.0  # ahead of the real clock, so deadlines hold
        self.t0 = self.t

    def monotonic(self):
        return self.t

    def sleep(self, seconds):
        self.t += max(0.0, seconds)

    def wall(self):
        return EPOCH + (self.t - self.t0)


def iso(epoch):
    return stamp(epoch)


def crc(*parts):
    return zlib.crc32("|".join(map(str, parts)).encode())


class FakeSqs:
    def __init__(self, world):
        self.world = world

    def get_queue_attributes(self, QueueUrl, AttributeNames):
        name = self.world.queue_of(QueueUrl)
        return {"Attributes": {
            "ApproximateNumberOfMessages": str(len(self.world.dlq[name])),
            "ApproximateNumberOfMessagesNotVisible": "0"}}

    def send_message(self, QueueUrl, MessageBody):
        self.world.poison.append((self.world.clock.t, MessageBody))
        return {"MessageId": uuid.uuid4().hex}

    def receive_message(self, QueueUrl, **kwargs):
        self.world.move_poison()
        name = self.world.queue_of(QueueUrl)
        messages = [{"MessageId": uuid.uuid4().hex, "Body": body, "ReceiptHandle": f"h-{i}",
                     "Attributes": {"ApproximateReceiveCount": "5"}}
                    for i, body in enumerate(self.world.dlq[name])]
        return {"Messages": messages}

    def delete_message(self, QueueUrl, ReceiptHandle):
        name = self.world.queue_of(QueueUrl)
        self.world.dlq[name].pop(int(ReceiptHandle.split("-")[1]))


class SimWorld:
    def __init__(self, *, env="dc2-v1-sim", encode_seconds=45.0, start_seconds=20.0,
                 repair_seconds=90.0, requeue=True, awake=False, slow=1.0, faults=(),
                 poison_seconds=300.0):
        self.env, self.faults = env, set(faults)
        self.clock = VirtualClock()
        self.plan = operations.PlanTransport()
        self.encode, self.start, self.repair = encode_seconds, start_seconds, repair_seconds
        self.requeue, self.slow, self.poison_seconds = requeue, slow, poison_seconds
        self.users, self.reservations, self.jobs, self.tasks = {}, {}, {}, {}
        self.definitions, self.logs, self.calls = {}, {}, []
        self.dlq = {q: [] for q in operations.QUEUES}
        self.poison = []
        # Aurora: capacity is 0.5 ACU for 5.5 minutes after the last use, then 0 (paused).
        self.last_use = None if not awake else self.clock.t
        self.registered, self.generated = 0, None

    # ---- plumbing --------------------------------------------------------------------
    def queue_of(self, url):
        return next(q for q in operations.QUEUES if url.endswith((q + "Queue", q + "Dlq")))

    def use_database(self):
        self.last_use = self.clock.t

    def move_poison(self):
        for sent, body in list(self.poison):
            if self.clock.t - sent >= self.poison_seconds:
                self.dlq["ProcessingCommands"].append(body)
                self.poison.remove((sent, body))

    def outputs(self):
        queues = {}
        for q in operations.QUEUES:
            queues[f"{q}QueueUrl"] = f"https://sqs.{REGION}.amazonaws.com/{ACCOUNT}/{q}Queue"
            queues[f"{q}DlqUrl"] = f"https://sqs.{REGION}.amazonaws.com/{ACCOUNT}/{q}Dlq"
            queues[f"{q}DlqArn"] = f"arn:aws:sqs:{REGION}:{ACCOUNT}:{q}Dlq"
        names = {f"{h}FunctionName": f"{self.env}-{h}" for h in operations.HANDLERS}
        names |= {f"{h}MappingId": str(uuid.uuid5(uuid.NAMESPACE_URL, h))
                  for h in operations.MAPPINGS}
        names |= {f"{h}RuleName": f"{self.env}-{h}" for h in operations.RULES}
        return {
            **queues, **names, "HttpApiId": "abc123def4", "HttpApiUrl": GATEWAY,
            "FrontendUrl": FRONTEND, "DistributionId": "E1SIMULATED",
            "SourceBucketName": "dc2-sim-source",
            "ClusterArn": f"arn:aws:ecs:{REGION}:{ACCOUNT}:cluster/{self.env}",
            "WorkerTaskDefinitionArn":
                f"arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/{self.env}-worker:1",
            "PublicTaskSubnetIds": "subnet-0a,subnet-0b", "WorkerSecurityGroupId": "sg-0w",
            "MigrationSecurityGroupId": "sg-0m",
        }

    # ---- public API over HTTP -----------------------------------------------------------
    def http(self, method, url, headers, body, timeout):
        parts = urlsplit(url)
        host, path = parts.hostname, parts.path or "/"
        self.clock.sleep(0.03)
        if host.endswith("amazonaws.com") and ".s3." in host:
            return self.s3(method, parts, headers, body)
        if host.startswith("sqs."):
            if "sqs-open" in self.faults:
                return 200, {}, b"<SendMessageResponse/>"
            return 403, {}, b"<Error><Code>MissingAuthenticationToken</Code></Error>"
        origin = "cloudfront" if host.endswith("cloudfront.net") else "gateway"
        return self.api(method, origin, path, parse_qs(parts.query), headers, body)

    def reply(self, status, payload=None, headers=None, raw=None, origin="gateway"):
        out = {k.lower(): [v] if isinstance(v, str) else v for k, v in (headers or {}).items()}
        if origin == "cloudfront":
            out["x-cache"] = ["Miss from cloudfront"]
        body = raw if raw is not None else json.dumps(payload).encode()
        return status, out, body

    def user_of(self, headers):
        cookie = headers.get("cookie", "")
        found = next((u for u in self.users.values() if f"sim-{u['id']}" in cookie), None)
        return found

    def api(self, method, origin, path, query, headers, body):
        self.tick()
        reply = lambda *a, **k: self.reply(*a, origin=origin, **k)  # noqa: E731
        if path == "/api/media/health":
            return reply(200, {"status": "ok", "service": "media"})
        if path == "/api/processing/health":
            return reply(200, {"status": "ok", "service": "processing", "schema_version": 1})
        data = json.loads(body) if body and headers.get("content-type") == "application/json" \
            else {}
        if path == "/api/media/auth/register":
            self.use_database()
            uid = uuid.uuid4().hex
            self.users[data["email"]] = {"id": uid, "password": data["password"]}
            return reply(201, {"id": uid})
        if path == "/api/media/auth/login":
            self.use_database()
            user = self.users.get(data.get("email"))
            if not user or user["password"] != data.get("password"):
                return reply(401, {"error": "bad credentials"})
            self.clock.sleep(0.25 * self.slow)
            flags = COOKIE.replace("sim-token", "sim-" + user["id"])
            if "weak-cookie" in self.faults:
                flags = flags.replace("; HttpOnly", "")
            return reply(200, {"id": user["id"]}, {"set-cookie": [flags]})
        if method == "OPTIONS":
            return reply(204, raw=b"")
        user = self.user_of(headers)
        if user is None:
            return reply(401, {"error": "unauthorized"})
        if path == "/api/media/auth/me":
            return reply(200, {"id": user["id"]})
        if path.startswith("/api/media/admin"):
            return reply(403, {"error": "forbidden"})
        if path == "/api/media/jobs":
            self.use_database()
            self.clock.sleep(0.04 * self.slow + (crc(path, self.clock.t // 1) % 30) / 1000)
            mine = [self.job_view(j) for j in self.jobs.values() if j["owner"] == user["id"]]
            return reply(200, mine)
        if path.startswith("/api/processing/jobs"):
            return reply(200, [])
        if path == "/api/media/uploads/reservations":
            # Like Media, a reservation is idempotent on (owner, request_id) and a replay of a
            # finalized one carries no upload grant.
            rid = next((r for r, found in self.reservations.items()
                        if found["owner"] == user["id"]
                        and found["request"]["request_id"] == data["request_id"]), None)
            if rid is None:
                rid = str(uuid.uuid4())
                self.reservations[rid] = {"owner": user["id"], "request": data,
                                          "uploaded": False}
            grant = None if self.reservations[rid].get("job") else {
                "url": f"https://{S3_HOST}/", "fields": {"key": rid, "policy": "p"}}
            return reply(201, {
                "reservation_id": rid, "expires_at": "2026-10-17T11:00:00Z",
                "finalize_url": f"/uploads/reservations/{rid}/finalize", "upload": grant})
        if path.startswith("/api/media/uploads/reservations/") and path.endswith("/finalize"):
            return self.finalize(path.split("/")[-2], user, reply)
        parts = path.split("/")
        if len(parts) >= 5 and parts[3] == "jobs" and parts[1:3] == ["api", "media"]:
            return self.job_route(parts, user, reply)
        return reply(404, {"error": "not found"})

    def finalize(self, rid, user, reply):
        found = self.reservations.get(rid)
        if not found or not found["uploaded"]:
            return reply(409, {"error": "no upload"})
        job_id = found.get("job") or str(uuid.uuid4())
        found["job"] = job_id
        self.jobs.setdefault(job_id, {
            "id": job_id, "owner": user["id"], "filename": found["request"]["filename"],
            "status": "queued", "queued_at": self.clock.t, "task": None})
        return reply(202, {"job_id": job_id})

    def job_view(self, job):
        view = {"id": job["id"], "filename": job["filename"], "status": job["status"],
                "submission_status": "submitted"}
        if job["status"] == "done":
            view["output_url"] = f"https://{S3_HOST}/out.mp4?X-Amz-Signature=sim"
            if "no-hls" not in self.faults:
                view["hls_url"] = f"/api/media/jobs/{job['id']}/hls/master.m3u8"
        return view

    def job_route(self, parts, user, reply):
        job = self.jobs.get(parts[4])
        if not job or job["owner"] != user["id"]:
            return reply(404, {"error": "not found"})
        if len(parts) == 5:
            return reply(200, self.job_view(job))
        name = "/".join(parts[6:])
        if job["status"] != "done":
            return reply(404, {"error": "not found"})
        if name == "master.m3u8":
            return reply(200, raw=b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nv0/index.m3u8\n",
                         headers={"cache-control": "private, no-store"})
        if name == "v0/index.m3u8":
            return reply(200, raw=b"#EXTM3U\n#EXTINF:2,\nseg0.ts\n#EXT-X-ENDLIST\n",
                         headers={"cache-control": "private, no-store"})
        if name == "v0/seg0.ts":
            return reply(307, raw=b"", headers={
                "location": f"https://{S3_HOST}/seg0.ts?X-Amz-Signature=sim"})
        return reply(404, {"error": "not found"})

    def s3(self, method, parts, headers, body):
        if method == "OPTIONS":
            origin = headers.get("origin", "")
            if origin == FRONTEND or "cors-open" in self.faults:
                return 200, {"access-control-allow-origin": [origin],
                             "access-control-allow-methods": ["POST"]}, b""
            return 403, {}, b""
        if method == "POST":
            assert "cookie" not in headers, "the session must never reach storage"
            rid = next((r for r in self.reservations if r.encode() in body), None)
            if rid is None or b"filename=" not in body:
                return 403, {}, b""
            self.reservations[rid]["uploaded"] = True
            self.clock.sleep(1.2)
            return 204, {}, b""
        if method == "GET" and "X-Amz-Signature" in parts.query:
            size = int(headers.get("range", "bytes=0-1023").split("-")[1]) + 1
            return 206, {"content-type": ["video/mp2t"]}, b"x" * size
        return 403, {}, b""

    # ---- encoder tasks -----------------------------------------------------------------------
    def tick(self):
        """Advance every task and job to the current virtual time."""
        now = self.clock.t
        for job in self.jobs.values():
            if job["status"] == "processing":
                task = self.tasks.get(job["task"])
                if task and task["stopped_at"] is not None and task.get("interrupted"):
                    if now >= task["stopped_at"] + self.repair:
                        job["status"], job["task"] = ("queued" if self.requeue else "failed"), None
                elif task and now >= job["finish_at"]:
                    job["status"] = "done"
                    task["busy"], task["idle_since"] = None, job["finish_at"]
        for task in self.tasks.values():
            if task["kind"] != "worker" or task["stopped_at"] is not None:
                continue
            if task["busy"] is None and now >= task["started_at"]:
                queued = sorted((j for j in self.jobs.values() if j["status"] == "queued"),
                                key=lambda j: j["queued_at"])
                if queued:
                    job = queued[0]
                    job.update(status="processing", task=task["arn"],
                               finish_at=max(now, task["started_at"]) + self.encode)
                    task["busy"] = job["id"]
                elif now >= task["idle_since"] + 40:
                    task["stopped_at"] = task["idle_since"] + 40
            if task["busy"] is None and task["stopped_at"] is None:
                task["idle_since"] = max(task["idle_since"], task["started_at"])
        for task in self.tasks.values():
            if task["kind"] != "worker" and task["stopped_at"] is None \
                    and now >= task["started_at"] + task["script_seconds"]:
                task["stopped_at"] = task["started_at"] + task["script_seconds"]

    def task_view(self, task):
        now = self.clock.t
        stopped = task["stopped_at"] is not None and now >= task["stopped_at"]
        status = "STOPPED" if stopped else (
            "RUNNING" if now >= task["started_at"] else "PROVISIONING")
        view = {"taskArn": task["arn"], "taskDefinitionArn": task["definition"],
                "lastStatus": status, "cpu": task["cpu"], "memory": task["memory"],
                "createdAt": iso(self.wall_of(task["created_at"])),
                "pullStartedAt": iso(self.wall_of(task["created_at"] + 2)),
                "containers": [{"exitCode": 0 if stopped else None,
                                "imageDigest": "sha256:" + "ab" * 32}]}
        if status != "PROVISIONING":
            view["startedAt"] = iso(self.wall_of(task["started_at"]))
        if stopped:
            view.update(stoppedAt=iso(self.wall_of(task["stopped_at"])),
                        stopCode="UserInitiated" if task.get("interrupted")
                        else "EssentialContainerExited")
        return view

    def wall_of(self, monotonic):
        return EPOCH + (monotonic - self.clock.t0)

    # ---- control plane ------------------------------------------------------------------------
    def call(self, service, operation, payload, *, deadline=None):
        self.calls.append((service, operation))
        self.tick()
        handler = getattr(self, f"{service}_{operation}".replace("-", "_"), None)
        if handler:
            return handler(payload)
        return self.plan.call(service, operation, payload, deadline=time.monotonic() + 600)

    def sts_get_caller_identity(self, payload):
        return {"Account": ACCOUNT, "Arn": f"arn:aws:iam::{ACCOUNT}:user/simulated"}

    def ecs_run_task(self, payload):
        arn = f"arn:aws:ecs:{REGION}:{ACCOUNT}:task/{self.env}/{uuid.uuid4().hex[:16]}"
        definition = payload["taskDefinition"]
        env = {e["name"]: e["value"] for c in payload.get("overrides", {}).get(
            "containerOverrides", []) for e in c.get("environment", [])}
        spec = self.definitions.get(definition, {})
        kind = "worker"
        if "DC2_SCRIPT" in env or "DC2_SCRIPT" in json.dumps(spec):
            kind = "generator" if "DC2_BASE_URL" in json.dumps(spec) else "probe"
        now = self.clock.t
        task = {"arn": arn, "definition": definition, "kind": kind, "created_at": now,
                "started_at": now + self.start, "stopped_at": None, "busy": None,
                "idle_since": now + self.start, "interrupted": False, "script_seconds": 30,
                "cpu": payload.get("overrides", {}).get("cpu", spec.get("cpu", "2048")),
                "memory": payload.get("overrides", {}).get("memory", spec.get("memory", "4096"))}
        if kind == "generator":
            task["script_seconds"] = 330
            self.logs[("/dc2/tasks", f"generator/generator/{arn.rsplit('/', 1)[-1]}")] = \
                self.generator_lines  # computed on first read: it replays 5 minutes of load
        elif kind == "probe":
            self.logs[("/dc2/tasks", f"Worker/worker/{arn.rsplit('/', 1)[-1]}")] = \
                self.probe_lines()
        self.tasks[arn] = task
        return {"tasks": [{"taskArn": arn}], "failures": []}

    def ecs_describe_tasks(self, payload):
        return {"tasks": [self.task_view(self.tasks[a]) for a in payload["tasks"]
                          if a in self.tasks], "failures": []}

    def ecs_list_tasks(self, payload):
        want = payload.get("desiredStatus", "RUNNING")
        return {"taskArns": [a for a, t in self.tasks.items()
                             if (self.task_view(t)["lastStatus"] == "STOPPED") == (
                                 want == "STOPPED")]}

    def ecs_stop_task(self, payload):
        task = self.tasks[payload["task"]]
        if task["stopped_at"] is None:
            task.update(stopped_at=self.clock.t, interrupted=True)
        return {}

    def ecs_describe_task_definition(self, payload):
        spec = self.definitions.get(payload["taskDefinition"])
        group = "/dc2/tasks"
        if spec:
            return {"taskDefinition": spec}
        return {"taskDefinition": {
            "taskDefinitionArn": payload["taskDefinition"], "family": f"{self.env}-worker",
            "cpu": "2048", "memory": "4096",
            "executionRoleArn": f"arn:aws:iam::{ACCOUNT}:role/{self.env}-exec",
            "runtimePlatform": {"cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX"},
            "containerDefinitions": [{
                "name": "worker", "image": f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/w@sha256:"
                + "cd" * 32,
                "logConfiguration": {"logDriver": "awslogs", "options": {
                    "awslogs-group": group, "awslogs-region": REGION,
                    "awslogs-stream-prefix": "Worker"}}}]}}

    def ecs_register_task_definition(self, payload):
        self.registered += 1
        family = f"task-definition/{payload['family']}:{self.registered}"
        arn = f"arn:aws:ecs:{REGION}:{ACCOUNT}:{family}"
        self.definitions[arn] = {**payload, "taskDefinitionArn": arn}
        return {"taskDefinition": {"taskDefinitionArn": arn}}

    def ecs_deregister_task_definition(self, payload):
        self.definitions[payload["taskDefinition"]]["status"] = "INACTIVE"
        return {}

    def logs_get_log_events(self, payload):
        lines = self.logs.get((payload["logGroupName"], payload["logStreamName"]), [])
        if callable(lines):
            if self.generated is None:
                self.generated = lines()
            lines = self.generated
        return {"events": [{"timestamp": 0, "message": m} for m in lines],
                "nextForwardToken": "end"}

    def probe_lines(self):
        result = {"own_database": "connected", "own_ddl": "denied:InsufficientPrivilegeError",
                  "other_database": "connect-denied:InvalidAuthorizationSpecificationError",
                  "other_database_read": None}
        if "crossdb-open" in self.faults:
            result.update(own_ddl="ALLOWED", other_database="reached",
                          other_database_read="ALLOWED")
        if "db-unreachable" in self.faults:
            result = {"own_database": "connect-denied:TimeoutError"}
        return ["start", "DC2-RESULT " + json.dumps(result)]

    def generator_lines(self):
        """Run the real generator against a latency model on its own virtual clock."""
        clock, world = VirtualClock(), self

        def request(user, method, path, cookie=None, body=None):
            base = 40 if "health" not in path else 20
            if method == "POST":
                base = 280
            ms = (base + crc(path, user, int(clock.t)) % 60) * world.slow
            if "slow-tail" in world.faults and crc(user, int(clock.t)) % 6 == 0:
                ms += 900
            cookies = [COOKIE] if "auth/" in path else []
            status = 201 if path.endswith("register") else 200
            if "errors" in world.faults and crc(user, int(clock.t)) % 20 == 0:
                status = 500
            return status, ms, cookies, b""

        sink = io.StringIO()
        with contextlib.redirect_stdout(sink):
            generator.run(
                {"users": 50, "seconds": 180, "warmup": 5, "other_seconds": 20, "logins": 20},
                request, clock.monotonic, clock.sleep, generator.emit)
        return sink.getvalue().splitlines()

    def capacity_at(self, minute):
        """0.5 ACU for 5.5 minutes after the database was last used, otherwise paused at 0."""
        if "never-pauses" in self.faults:
            return 0.5
        moment = self.clock.t0 + (minute - EPOCH)
        used = self.last_use
        return 0.5 if used is not None and used <= moment < used + 330 else 0.0

    def cloudwatch_get_metric_statistics(self, payload):
        start, end = int(parse_epoch(payload["StartTime"])), int(parse_epoch(payload["EndTime"]))
        now = self.clock.wall()
        points = []
        for minute in range(start - start % 60 + 60, end, 60):
            if minute <= now:
                value = self.capacity_at(minute)
                points.append({"Timestamp": iso(minute), "Minimum": value, "Maximum": value})
        return {"Datapoints": points, "Label": "ServerlessDatabaseCapacity"}

    def rds_describe_db_clusters(self, payload):
        return {"DBClusters": [{"ServerlessV2ScalingConfiguration": {
            "MinCapacity": 0.0, "MaxCapacity": 2.0, "SecondsUntilAutoPause": 300}}]}

    def ce_get_cost_and_usage(self, payload):
        groups = {"Amazon Relational Database Service": "1.62", "Amazon Elastic Container Service":
                  "0.41", "AWS Lambda": "0.03", "Amazon CloudFront": "0.0", "Amazon Simple "
                  "Storage Service": "0.02", "EC2 - Other": "0.11", "Amazon Simple Queue "
                  "Service": "0.0", "AWS Secrets Manager": "0.2"}
        return {"ResultsByTime": [{"Estimated": True, "Groups": [
            {"Keys": [k], "Metrics": {"UnblendedCost": {"Amount": v, "Unit": "USD"}}}
            for k, v in groups.items()]}]}


def parse_epoch(text):
    from scripts.aws.v1.proof.core import parse_time

    return parse_time(text).timestamp()


def build(args, *, session="open", world=None, sql=True, tmp=None):
    """A simulated Context over real private files in a throwaway state directory."""
    import tempfile

    world = world or SimWorld()
    folder = Path(tmp or tempfile.mkdtemp(prefix="dc2-proof-sim-"))
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder.chmod(0o700)
    (folder / "session").mkdir(mode=0o700, exist_ok=True)
    outputs = world.outputs()
    (folder / "outputs.json").write_text(json.dumps(outputs))
    config = {"operator_station": "sim-station", "environment_id": world.env,
              "journal": str(folder / "session" / "journal.json"),
              "outputs_file": str(folder / "outputs.json")}
    if sql:
        config["sql"] = {"ca_file": "/dev/null", "media_dsn_file": "/dev/null",
                         "processing_dsn_file": "/dev/null"}
    (folder / "operator-config.json").write_text(json.dumps(config))
    creds = folder / "smoke-credentials.json"
    creds.write_text(json.dumps({"email": "smoke@example.com", "password": "sim-password"}))
    creds.chmod(0o600)
    world.users["smoke@example.com"] = {"id": "smoke-user", "password": "sim-password"}
    data, cfg, hooks, urls, outputs, journal = load_state(folder)
    deploy_journal = DeployJournal(folder / "deploy-journal.json", station="sim-station",
                                   environment=world.env)
    deploy_journal.create({"run_id": "sim", "env": world.env, "steps": {}, "outputs": {},
                           "images": {}, "events": [],
                           "resources": {"db_clusters": ["sim-cluster"]}})
    journal.initialize(verified_empty=True, exclusive_station=True)
    if session != "closed":
        with journal.locked() as state:
            state.update(session=session, paused=False)
            journal.save(state)
        world.plan.stage = dict(OPEN_EDGE)
    return Context(
        scope={"profile": "dc2-project2-mfa", "region": REGION, "account": ACCOUNT},
        state_dir=folder, run_id=getattr(args, "run_id", "sim"), simulated=True,
        outputs=outputs, config=cfg, hooks=hooks, urls=urls, data=data, journal=journal,
        aws=world, http=world.http, clock=world.clock.monotonic, sleep=world.clock.sleep,
        wall=world.clock.wall,
        credentials=lambda: json.loads(creds.read_text()), sqs=lambda: FakeSqs(world),
        sdk=lambda scope: world, release_main=release_cli.main, world=world)

