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
import datetime as dt
import hashlib
import io
import json
import re
import time
import uuid
import zlib
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from scripts.aws.v1 import operations, release_cli
from scripts.aws.v1.deploy import DeployJournal
from scripts.aws.v1.proof import generator
from scripts.aws.v1.proof.context import Context, load_state
from scripts.aws.v1.proof.core import stamp
from scripts.aws.v1.transport import REGION
from scripts.ci.v1_scan import scan_receipt

LOCAL_ID = {
    "media": "sha256:" + "11" * 32,
    "processing": "sha256:" + "22" * 32,
    "worker": "sha256:" + "33" * 32,
}


def image_manifest(config_id):
    return json.dumps({"schemaVersion": 2, "config": {"digest": config_id}}, indent=2)


BASELINE_DIGEST = {
    name: "sha256:" + hashlib.sha256(image_manifest(config).encode()).hexdigest()
    for name, config in LOCAL_ID.items()
}
EPOCH = 1_792_233_600.0  # 2026-10-17T10:40:00Z, an arbitrary fixed wall-clock origin
ACCOUNT = "123456789012"
FRONTEND = "https://d111111abcdef8.cloudfront.net"
GATEWAY = "https://abc123def4.execute-api.ap-southeast-1.amazonaws.com"
S3_HOST = "dc2-sim-source.s3.ap-southeast-1.amazonaws.com"
# The throttle an operator sets (`edge_open` in operator-config.json) for the 50-user latency load.
EDGE_OPEN = {"rate": 100, "burst": 200}
OPEN_EDGE = {"ThrottlingBurstLimit": EDGE_OPEN["burst"], "ThrottlingRateLimit": EDGE_OPEN["rate"]}
COOKIE = "session=sim-token; HttpOnly; Secure; SameSite=Strict; Path=/"
MAX_BYTES = 100 * 1024 * 1024  # the product's upload limit (contracts.v1.MAX_UPLOAD_BYTES)
GRANT_SECONDS = 900  # a reservation's grant lives 15 minutes (media/services/direct_intake.py)
SIGNED_SECONDS = 900  # a signed GET lives signed_url_ttl_seconds (media/config.py default)


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


def iso_precise(epoch):
    """Sub-second ISO stamps, like the Processing API's timestamptz columns."""
    return dt.datetime.fromtimestamp(epoch, dt.UTC).isoformat()


def crc(*parts):
    return zlib.crc32("|".join(map(str, parts)).encode())


class FakeSqs:
    def __init__(self, world):
        self.world = world

    def get_queue_attributes(self, QueueUrl, AttributeNames):
        name = self.world.queue_of(QueueUrl)
        if not QueueUrl.endswith("Dlq"):
            # A main queue: the commands queue holds what Media published and Processing has
            # not consumed; the others are not modelled and read empty.
            depth = {
                "ProcessingCommands": self.world.commands_waiting(),
                "ProcessingWork": self.world.stale_work,
            }.get(name, 0)
            return {
                "Attributes": {
                    "ApproximateNumberOfMessages": str(depth),
                    "ApproximateNumberOfMessagesNotVisible": "0",
                    "ApproximateNumberOfMessagesDelayed": "0",
                }
            }
        return {
            "Attributes": {
                "ApproximateNumberOfMessages": str(len(self.world.dlq.get(name, []))),
                "ApproximateNumberOfMessagesNotVisible": "0",
            }
        }

    def send_message(self, QueueUrl, MessageBody):
        self.world.poison.append((self.world.clock.t, MessageBody))
        return {"MessageId": uuid.uuid4().hex}

    def receive_message(self, QueueUrl, **kwargs):
        self.world.move_poison()
        name = self.world.queue_of(QueueUrl)
        messages = [
            {
                "MessageId": uuid.uuid4().hex,
                "Body": body,
                "ReceiptHandle": f"h-{i}",
                "Attributes": {"ApproximateReceiveCount": "5"},
            }
            for i, body in enumerate(self.world.dlq[name])
        ]
        return {"Messages": messages}

    def delete_message(self, QueueUrl, ReceiptHandle):
        name = self.world.queue_of(QueueUrl)
        self.world.dlq[name].pop(int(ReceiptHandle.split("-")[1]))


class SimWorld:
    def __init__(
        self,
        *,
        env="dc2-v1-sim",
        encode_seconds=45.0,
        start_seconds=20.0,
        repair_seconds=90.0,
        requeue=True,
        awake=False,
        slow=1.0,
        faults=(),
        poison_seconds=300.0,
        lambda_lane=False,
        lambda_cold_seconds=9.0,
        lambda_warm_seconds=4.0,
        database=None,
        resume_seconds=30.0,
        probe_ms=45.0,
        shared_load_slowdown=1.8,
        auto_pause_seconds=300,
        max_acu=2.0,
        one_job_per_task=True,
        fail_claims=(),
        outbox_seconds=0.0,
        launcher=False,
        launcher_tick_seconds=60.0,
        dud_encoders=0,
        stale_work=0,
    ):
        self.env, self.faults = env, set(faults)
        # The first `dud_encoders` worker tasks exit 0 a few seconds after starting without
        # claiming anything (r1018b: an encoder that long-polled before the command arrived).
        # `stale_work` is how many messages an earlier run left in the ProcessingWork queue.
        self.dud_encoders, self.stale_work, self.workers_started = dud_encoders, stale_work, 0
        # V1 encoders are finite: a task claims one attempt, encodes it and exits (processing/
        # worker/sqs.py). `False` keeps the older model where a task keeps taking queued jobs.
        # `fail_claims` lists the 1-based claim numbers whose encode ends `failed`.
        self.one_job_per_task, self.fail_claims, self.claims = one_job_per_task, set(fail_claims), 0
        # Media publishes a finalized upload's command `outbox_seconds` later (its repair rule);
        # the ProcessingCommands mapping then delivers it to Processing only while Enabled.
        self.outbox_seconds = outbox_seconds
        self.commands_mapping = str(uuid.uuid5(uuid.NAMESPACE_URL, "ProcessingCommands"))
        # A stack deployed with UnattendedLaunch=true; it starts encoders only while the rule is
        # ENABLED, which `build(..., unattended=True)` does like `session open --unattended`.
        self.launcher, self.launcher_tick, self.next_launch = launcher, launcher_tick_seconds, None
        self.clock = VirtualClock()
        self.plan = operations.PlanTransport()
        self.encode, self.start, self.repair = encode_seconds, start_seconds, repair_seconds
        self.requeue, self.slow, self.poison_seconds = requeue, slow, poison_seconds
        self.users, self.reservations, self.jobs, self.tasks = {}, {}, {}, {}
        # A release that keeps an image retags its running manifest; an adopted release is what
        # the stack's own definitions then hold (V2-live).
        self.retagged, self.stack_digests = {}, dict(BASELINE_DIGEST)
        self.manifests = {
            BASELINE_DIGEST[name]: image_manifest(config) for name, config in LOCAL_ID.items()
        }
        self.definitions, self.logs, self.calls = {}, {}, []
        self.dlq = {q: [] for q in operations.QUEUES}
        self.poison = []
        # Aurora: capacity is 0.5 ACU for 5.5 minutes after the last use, then 0 (paused).
        self.last_use = None if not awake else self.clock.t
        self.registered, self.generated = 0, None
        # ECR scan findings as (name, severity) pairs, served `scan_page` per reply with a
        # nextToken; None keeps the counts-only reply the older harnesses use.
        self.scan_findings, self.scan_page = None, 100
        # The opt-in Lambda short-encode lane (#93): a stack WITH it runs queued jobs in
        # invocations (two at once, like the mapping), a stack without it never does.
        self.lambda_lane, self.lambda_seconds = (
            lambda_lane,
            (lambda_cold_seconds, lambda_warm_seconds),
        )
        self.invocations, self.last_invocation = [], None
        # The opt-in database layout (#94). None keeps the older harnesses' single always-on
        # cluster model; "shared" or "separate" gives each cluster its own pause, resume and
        # load history, and a shared cluster slows its other domain while one is under load.
        self.database, self.resume_seconds, self.probe_ms = database, resume_seconds, probe_ms
        self.shared_load_slowdown = shared_load_slowdown
        self.auto_pause_seconds, self.max_acu = auto_pause_seconds, max_acu
        self.busy, self.resuming, self.loads, self.probes = {}, {}, {}, 0
        # What the in-VPC reader (#150) finds: each owner's Alembic head and Processing's
        # attempt counts, read by a finite task that runs the owner's migration definition.
        self.schema = {"media": "m0007", "processing": "p0005"}
        self.attempt_counts = {
            "queued": 0,
            "processing": 0,
            "succeeded": 3,
            "failed": 1,
            "abandoned": 0,
            "cancelled": 0,
        }
        self.vpc_reads = []
        # The security proof (#229): the upload limit the simulated Media enforces, and the
        # addresses and ports the simulated CloudFront edge answers on.
        self.max_bytes = MAX_BYTES
        self.open_ports = {80, 443} | ({8080} if "port-8080-open" in self.faults else set())
        if lambda_lane:  # a full `session open` has enabled every mapping
            self.plan.mappings[str(uuid.uuid5(uuid.NAMESPACE_URL, "ProcessingShortEncoder"))] = (
                "Enabled"
            )

    # ---- plumbing --------------------------------------------------------------------
    def queue_of(self, url):
        if "ProcessingShortWork" in url:
            return "ProcessingShortWork"
        return next(q for q in operations.QUEUES if url.endswith((q + "Queue", q + "Dlq")))

    def use_database(self):
        self.last_use = self.clock.t

    # ---- clusters (database mode) ---------------------------------------------------------
    def cluster_ids(self):
        if self.database == "separate":
            return {"media": "sim-media-cluster", "processing": "sim-processing-cluster"}
        return {"cluster": "sim-cluster"}

    def cluster_of(self, domain):
        ids = self.cluster_ids()
        return ids.get(domain, ids.get("cluster"))

    def touch(self, cluster, start=None, end=None):
        now = self.clock.t
        self.busy.setdefault(cluster, []).append(
            (now if start is None else start, now if end is None else end)
        )

    def awake(self, cluster, moment):
        """In use now or inside the pause timer after the last use (loads are open intervals)."""
        if any(self.cluster_of(domain) == cluster for domain in self.loads):
            return True
        return any(
            start <= moment < end + self.auto_pause_seconds + 30
            for start, end in self.busy.get(cluster, [])
        )

    def begin_load(self, domain, concurrency):
        self.loads[domain] = (concurrency, self.clock.t)
        self.touch(self.cluster_of(domain))

    def end_load(self, domain):
        _, started = self.loads.pop(domain)
        self.touch(self.cluster_of(domain), start=started, end=self.clock.t)

    def lambda_invoke(self, payload):
        """The owner's ready probe against a modelled cluster; anything else is the plan's."""
        event = payload["Payload"]
        if self.database is None or event.get("dc2_operation") != "ready":
            return self.plan.call("lambda", "invoke", payload, deadline=time.monotonic() + 600)
        domain = "media" if "Media" in payload["FunctionName"] else "processing"
        cluster, now = self.cluster_of(domain), self.clock.t
        if cluster not in self.resuming and not self.awake(cluster, now):
            self.resuming[cluster] = now + self.resume_seconds
        if cluster in self.resuming:
            self.touch(cluster)
            if now < self.resuming[cluster]:
                self.clock.sleep(8)  # a probe that rides a resume waits, then reports not ready
                return {
                    "StatusCode": 200,
                    "FunctionError": False,
                    "Payload": {"service": domain, "ready": False},
                }
            del self.resuming[cluster]
        self.touch(cluster)
        self.probes += 1
        jitter = 1 + (crc("probe", self.probes) % 21) / 100
        peer = "processing" if domain == "media" else "media"
        coupled = self.database == "shared" and peer in self.loads
        self.clock.sleep(
            self.probe_ms / 1000 * jitter * (self.shared_load_slowdown if coupled else 1.0)
        )
        return {
            "StatusCode": 200,
            "FunctionError": False,
            "Payload": {"service": domain, "ready": True},
        }

    def journal_resources(self):
        ids = self.cluster_ids() if self.database else {"cluster": "sim-cluster"}
        logical = {
            "cluster": "DatabaseCluster",
            "media": "MediaDatabaseCluster",
            "processing": "ProcessingDatabaseCluster",
        }
        return {
            "db_clusters": list(ids.values()),
            "db_logical": {cid: logical[label] for label, cid in ids.items()},
        }

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
        names |= {
            f"{h}MappingId": str(uuid.uuid5(uuid.NAMESPACE_URL, h)) for h in operations.MAPPINGS
        }
        names |= {f"{h}RuleName": f"{self.env}-{h}" for h in operations.RULES}
        if self.lambda_lane:
            names |= {
                "ProcessingShortEncoderFunctionName": f"{self.env}-ProcessingShortEncoder",
                "ProcessingShortEncoderMappingId": str(
                    uuid.uuid5(uuid.NAMESPACE_URL, "ProcessingShortEncoder")
                ),
                "ProcessingShortWorkQueueUrl": f"https://sqs.{REGION}.amazonaws.com/{ACCOUNT}/ProcessingShortWorkQueue",
                "ProcessingShortWorkDlqUrl": f"https://sqs.{REGION}.amazonaws.com/{ACCOUNT}/ProcessingShortWorkDlq",
            }
        if self.launcher:
            names |= {
                "ProcessingLauncherFunctionName": f"{self.env}-ProcessingLauncher",
                "ProcessingLauncherRuleName": f"{self.env}-ProcessingLauncher-rule",
            }
        if self.database == "separate":
            names |= {
                "DatabaseTopology": "separate",
                "MediaDatabaseEndpoint": "media.cluster-sim.invalid",
                "ProcessingDatabaseEndpoint": "processing.cluster-sim.invalid",
            }
        elif self.database == "shared":
            names["DatabaseEndpoint"] = "shared.cluster-sim.invalid"
        return {
            **queues,
            **names,
            "OutputBucketName": "dc2-sim-output",
            "HttpApiId": "abc123def4",
            "HttpApiUrl": GATEWAY,
            "FrontendUrl": FRONTEND,
            "DistributionId": "E1SIMULATED",
            "SourceBucketName": "dc2-sim-source",
            "ClusterArn": f"arn:aws:ecs:{REGION}:{ACCOUNT}:cluster/{self.env}",
            "WorkerTaskDefinitionArn": (
                f"arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/{self.env}-worker:1"
            ),
            "PublicTaskSubnetIds": "subnet-0a,subnet-0b",
            "WorkerSecurityGroupId": "sg-0w",
            "MigrationSecurityGroupId": "sg-0m",
            **{
                f"{owner.title()}MigrationTaskDefinitionArn": self.migration_definition(owner)
                for owner in ("media", "processing")
            },
        }

    def migration_definition(self, owner):
        return f"arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/{self.env}-{owner}migration:1"

    # ---- the deployed images (#150: the release-plan helper reads them back) ---------------
    def repository(self, owner):
        return f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{self.env}-{owner}"

    def image_digest(self, repository, tag):
        """The registry's digest for a tag: a retag, the deployed baseline, else a made-up one."""
        if (repository, tag) in self.retagged:
            return self.retagged[(repository, tag)]
        owner = repository.rsplit("-", 1)[-1]
        if tag == f"{self.env}-{owner}" and owner in BASELINE_DIGEST:
            return BASELINE_DIGEST[owner]
        return "sha256:" + hashlib.sha256(f"{repository}:{tag}".encode()).hexdigest()

    def register_build(self, prefix, evidence, only=None):
        """Put a simulated build's exact configs/manifests into this in-memory registry."""
        for name, image in json.loads(Path(evidence).read_text())["images"].items():
            if only and name not in only:
                continue
            raw = image_manifest(image["config_id"])
            digest = "sha256:" + hashlib.sha256(raw.encode()).hexdigest()
            self.manifests[digest] = raw
            self.retagged[(self.repository(name), f"{prefix}-{name}")] = digest

    def journal_images(self):
        """What `deploy` recorded when it pushed the three images."""
        return {
            owner: {
                "local_id": LOCAL_ID[owner],
                "tag": f"{self.env}-{owner}",
                "digest": BASELINE_DIGEST[owner],
                "uri": f"{self.repository(owner)}@{BASELINE_DIGEST[owner]}",
                "scan_severity_counts": {"MEDIUM": 1},
            }
            for owner in ("media", "processing", "worker")
        }

    def journal_outputs(self):
        return {
            f"{owner.title()}RepositoryUri": self.repository(owner)
            for owner in ("media", "processing", "worker")
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
        if parts.scheme == "http":  # the edge redirects to HTTPS; execute-api has no port 80
            if origin != "cloudfront":
                raise ConnectionRefusedError
            return self.reply(
                301, raw=b"", headers={"location": f"https://{host}{path}"}, origin=origin
            )
        return self.api(method, origin, path, parse_qs(parts.query), headers, body)

    # ---- the network edge, for the port scan (#229) ---------------------------------------
    def resolve(self, host):
        return ["203.0.113.10", "203.0.113.11"]  # TEST-NET-3: documentation addresses

    def connect(self, address, port, timeout):
        if port in self.open_ports:
            return "open"
        return "filtered" if port % 2 else "closed"

    def signed(self, path, *, key=None):
        """A presigned GET for `path`: the signature binds path, date and lifetime."""
        date = dt.datetime.fromtimestamp(self.clock.wall(), dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        query = {
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Date": date,
            "X-Amz-Expires": SIGNED_SECONDS,
            "X-Amz-Signature": f"sim{crc(key or path, date, SIGNED_SECONDS):08x}",
        }
        return f"https://{S3_HOST}{path}?{urlencode(query)}"

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
        data = (
            json.loads(body) if body and headers.get("content-type") == "application/json" else {}
        )
        if path == "/api/media/auth/register":
            self.use_database()
            if data["email"] in self.users:
                return reply(409, raw=b"")
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
        if user is None and "gateway-anonymous-open" in self.faults and origin == "gateway":
            return reply(200, [])
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
        if path == "/api/processing/jobs":
            return reply(200, [])
        if path.startswith("/api/processing/jobs/"):
            job = next(
                (
                    j
                    for j in self.jobs.values()
                    if j["pid"] == path.rsplit("/", 1)[-1]
                    and j["owner"] == user["id"]
                    and j.get("delivered", True)
                ),
                None,
            )
            return (
                reply(200, self.processing_view(job)) if job else reply(404, {"error": "not found"})
            )
        if path == "/api/media/uploads/reservations":
            # Like Media, a reservation is idempotent on (owner, request_id) and a replay of a
            # finalized one carries no upload grant.
            rid = next(
                (
                    r
                    for r, found in self.reservations.items()
                    if found["owner"] == user["id"]
                    and found["request"]["request_id"] == data["request_id"]
                ),
                None,
            )
            if rid is None:
                if data["size_bytes"] > self.max_bytes and "oversize-open" not in self.faults:
                    return reply(422, {"error": "size_bytes too large"})
                rid = str(uuid.uuid4())
                self.reservations[rid] = {
                    "owner": user["id"],
                    "request": data,
                    "uploaded": False,
                    "expires_t": self.clock.t + GRANT_SECONDS,
                }
            found = self.reservations[rid]
            grant = (
                None
                if found.get("job")
                else {
                    "url": f"https://{S3_HOST}/",
                    "fields": {
                        "key": f"staging/{found['owner']}/{rid}/source",
                        "Content-Type": found["request"]["content_type"],
                        "policy": f"policy-{rid}",
                        "x-amz-signature": f"sig-{rid}",
                        "x-amz-credential": "sim",
                        "x-amz-date": "20261017T000000Z",
                    },
                }
            )
            return reply(
                201,
                {
                    "reservation_id": rid,
                    "expires_at": iso(self.wall_of(found["expires_t"])),
                    "finalize_url": f"/uploads/reservations/{rid}/finalize",
                    "upload": grant,
                },
            )
        if path.startswith("/api/media/uploads/reservations/") and path.endswith("/finalize"):
            return self.finalize(path.split("/")[-2], user, reply)
        parts = path.split("/")
        if len(parts) >= 5 and parts[3] == "jobs" and parts[1:3] == ["api", "media"]:
            return self.job_route(parts, user, reply)
        return reply(404, {"error": "not found"})

    def finalize(self, rid, user, reply):
        found = self.reservations.get(rid)
        if not found or found["owner"] != user["id"]:
            return reply(404, {"error": "not found"})
        if not found["uploaded"]:
            return reply(409, {"error": "no upload"})
        if found["stored_bytes"] > found["request"]["size_bytes"] and (
            "adopts-oversize" not in self.faults
        ):
            return reply(422, {"error": "source size does not match reservation"})
        if "finalize-needs-processing" in self.faults and not self.commands_enabled():
            return reply(503, {"error": "processing unavailable"})
        job_id = found.get("job") or str(uuid.uuid4())
        found["job"] = job_id
        self.jobs.setdefault(
            job_id,
            {
                "id": job_id,
                "pid": str(uuid.uuid4()),
                "owner": user["id"],
                "filename": found["request"]["filename"],
                "status": "queued",
                "queued_at": self.clock.t,
                "task": None,
                "submit_t": self.clock.t + self.outbox_seconds,
                "delivered": False,
            },
        )
        self.deliver(self.clock.t)
        return reply(202, {"job_id": job_id})

    def processing_view(self, job):
        """Processing's public job: the current attempt's server-side queue and run stamps."""
        done = job["status"] in {"done", "failed"}
        state = {
            "queued": "queued",
            "processing": "processing",
            "done": "succeeded",
            "failed": "failed",
        }[job["status"]]
        started, finished = job.get("started_t"), job.get("finished_t")
        return {
            "job_id": job["pid"],
            "processing_job_id": job["pid"],
            "status": job["status"],
            "current_attempt": {
                "attempt_id": str(uuid.uuid5(uuid.NAMESPACE_URL, job["pid"])),
                "number": 1,
                "state": state,
                "queued_at": iso_precise(self.wall_of(job["queued_at"])),
                "started_at": iso_precise(self.wall_of(started)) if started else None,
                "finished_at": iso_precise(self.wall_of(finished)) if done and finished else None,
                "error": None,
            },
        }

    def job_view(self, job):
        published = self.clock.t >= job.get("submit_t", 0)
        status = job["status"]
        if not job.get("delivered", True) and not published:
            status = "accepted"  # still in Media's outbox
        view = {
            "id": job["id"],
            "filename": job["filename"],
            "status": status,
            "submission_status": "submitted" if published else "pending",
            "processing_job_id": job.get("pid") if job.get("delivered", True) else None,
        }
        if job["status"] == "done":
            view["output_url"] = self.signed("/out.mp4")
            if "no-hls" not in self.faults:
                view["hls_url"] = f"/api/media/jobs/{job['id']}/hls/master.m3u8"
        return view

    def job_route(self, parts, user, reply):
        job = self.jobs.get(parts[4])
        if not job or (job["owner"] != user["id"] and "cross-owner-open" not in self.faults):
            return reply(404, {"error": "not found"})
        if len(parts) == 5:
            return reply(200, self.job_view(job))
        name = "/".join(parts[6:])
        if job["status"] != "done":
            return reply(404, {"error": "not found"})
        if name == "master.m3u8":
            return reply(
                200,
                raw=b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nv0/index.m3u8\n",
                headers={"cache-control": "private, no-store"},
            )
        if name == "v0/index.m3u8":
            return reply(
                200,
                raw=b"#EXTM3U\n#EXTINF:2,\nseg0.ts\n#EXT-X-ENDLIST\n",
                headers={"cache-control": "private, no-store"},
            )
        if name == "v0/seg0.ts":
            return reply(307, raw=b"", headers={"location": self.signed("/seg0.ts")})
        return reply(404, {"error": "not found"})

    def s3(self, method, parts, headers, body):
        if method == "OPTIONS":
            origin = headers.get("origin", "")
            if origin == FRONTEND or "cors-open" in self.faults:
                return (
                    200,
                    {
                        "access-control-allow-origin": [origin],
                        "access-control-allow-methods": ["POST"],
                    },
                    b"",
                )
            return 403, {}, b""
        if method == "POST":
            return self.s3_post(headers, body)
        if method == "GET" and "X-Amz-Signature" in parts.query:
            if not self.signed_get_ok(parts):
                return 403, {}, b"<Error><Code>SignatureDoesNotMatch</Code></Error>"
            size = int(headers.get("range", "bytes=0-1023").split("-")[1]) + 1
            return 206, {"content-type": ["video/mp2t"]}, b"x" * size
        if method == "GET" and "s3-listable" in self.faults:
            return 200, {}, b"<ListBucketResult/>"
        return 403, {}, b"<Error><Code>AccessDenied</Code></Error>"

    def signed_get_ok(self, parts):
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        if "tamper-open" in self.faults:
            return True
        date = query.get("X-Amz-Date", "")
        try:
            lifetime = int(query.get("X-Amz-Expires", ""))
        except ValueError:
            return False
        if query.get("X-Amz-Signature") != f"sim{crc(parts.path, date, lifetime):08x}":
            return False
        issued = dt.datetime.strptime(date, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.UTC)
        late = self.clock.wall() > issued.timestamp() + lifetime
        return not late or "expiry-open" in self.faults

    def s3_post(self, headers, body):
        """A presigned POST: signature, policy, key and content type are bound; size is capped."""
        assert "cookie" not in headers, "the session must never reach storage"
        text = body.decode("latin-1")
        fields = dict(re.findall(r'name="([^"]+)"\r\n\r\n(.*?)\r\n--', text, re.S))
        found = re.fullmatch(r"staging/[^/]+/([^/]+)/source", fields.get("key", ""))
        reservation = self.reservations.get(found.group(1)) if found else None
        if reservation is None or b"filename=" not in body:
            return 403, {}, b""
        rid = found.group(1)
        if "tamper-open" not in self.faults and (
            fields.get("x-amz-signature") != f"sig-{rid}"
            or fields.get("policy") != f"policy-{rid}"
            or fields.get("Content-Type") != reservation["request"]["content_type"]
        ):
            return 403, {}, b"<Error><Code>SignatureDoesNotMatch</Code></Error>"
        if self.clock.t > reservation["expires_t"] and "expiry-open" not in self.faults:
            return 403, {}, b"<Error><Code>AccessDenied</Code></Error>"
        boundary = headers["content-type"].split("boundary=")[1]
        start = body.index(b"\r\n\r\n", body.index(b'name="file"')) + 4
        stored = body.rindex(f"\r\n--{boundary}--\r\n".encode()) - start
        if stored > reservation["request"]["size_bytes"] and (
            "no-s3-limit" not in self.faults and "adopts-oversize" not in self.faults
        ):
            return 400, {}, b"<Error><Code>EntityTooLarge</Code></Error>"
        reservation["uploaded"], reservation["stored_bytes"] = True, stored
        self.clock.sleep(1.2)
        return 204, {}, b""

    # ---- encoder tasks -----------------------------------------------------------------------
    def tick(self):
        """Advance every task and job to the current virtual time."""
        now = self.clock.t
        self.deliver(now)
        self.tick_launcher(now)
        if self.lambda_lane:
            self.tick_lambda(now)
        for job in self.jobs.values():
            if job["status"] == "processing" and job.get("lambda"):
                continue
            if job["status"] == "processing":
                task = self.tasks.get(job["task"])
                if task and task["stopped_at"] is not None and task.get("interrupted"):
                    if now >= task["stopped_at"] + self.repair:
                        job["status"], job["task"] = ("queued" if self.requeue else "failed"), None
                elif task and now >= job["finish_at"]:
                    job["status"] = "failed" if job["claim_no"] in self.fail_claims else "done"
                    job["finished_t"] = job["finish_at"]
                    task["busy"], task["idle_since"] = None, job["finish_at"]
                    if self.one_job_per_task:
                        task["stopped_at"] = job["finish_at"] + 3.0  # the process exit lag
        for task in self.tasks.values():
            if task["kind"] != "worker" or task["stopped_at"] is not None:
                continue
            if task["busy"] is None and now >= task["started_at"]:
                queued = sorted(
                    (
                        j
                        for j in self.jobs.values()
                        if j["status"] == "queued" and j.get("delivered", True)
                    ),
                    key=lambda j: j["queued_at"],
                )
                if queued:
                    job = queued[0]
                    # The attempt starts when the worker is up and the job is queued, not when
                    # this lazy tick happens to notice it: the API's timestamps are server-side.
                    begin = max(task["idle_since"], job["queued_at"])
                    self.claims += 1
                    job.update(
                        status="processing",
                        task=task["arn"],
                        claim_no=self.claims,
                        started_t=begin,
                        finished_t=None,
                        finish_at=(begin if self.one_job_per_task else max(now, task["started_at"]))
                        + self.encode,
                    )
                    task["busy"] = job["id"]
                elif now >= task["idle_since"] + 40:
                    task["stopped_at"] = task["idle_since"] + 40
            if task["busy"] is None and task["stopped_at"] is None:
                task["idle_since"] = max(task["idle_since"], task["started_at"])
        for task in self.tasks.values():
            if (
                task["kind"] != "worker"
                and task["stopped_at"] is None
                and now >= task["started_at"] + task["script_seconds"]
            ):
                task["stopped_at"] = task["started_at"] + task["script_seconds"]

    def commands_enabled(self):
        return "mapping-ignored" in self.faults or (
            self.plan.mappings.get(self.commands_mapping) == "Enabled"
        )

    def commands_waiting(self):
        """Commands Media has published that Processing's consumer has not taken yet."""
        return sum(
            1
            for j in self.jobs.values()
            if not j.get("delivered", True) and self.clock.t >= j["submit_t"]
        )

    def deliver(self, now):
        """The ProcessingCommands mapping hands published commands to Processing, if Enabled."""
        if "stuck-consumer" in self.faults or not self.commands_enabled():
            return
        for job in self.jobs.values():
            if not job.get("delivered", True) and now >= job["submit_t"]:
                job["delivered"] = True
                # Delivered on the spot, or late (the consumer was off): then the attempt is
                # queued when this tick notices the mapping, not when Media published.
                job["queued_at"] = now if now - job["submit_t"] > 1.0 else job["submit_t"]

    def tick_launcher(self, now):
        """The opt-in launcher (#68): once a minute, start encoders for unclaimed queued work."""
        rule = f"{self.env}-ProcessingLauncher-rule"
        if not self.launcher or self.plan.rules.get(rule) != "ENABLED":
            self.next_launch = None
            return
        if "launcher-dead" in self.faults:  # enabled but never starts anything
            return
        if self.next_launch is None:
            self.next_launch = now + self.launcher_tick
        while now >= self.next_launch:
            at, self.next_launch = self.next_launch, self.next_launch + self.launcher_tick
            workers = [
                t
                for t in self.tasks.values()
                if t["kind"] == "worker" and (t["stopped_at"] is None or t["stopped_at"] > at)
            ]
            unclaimed = sum(1 for t in workers if t["busy"] is None)
            queued = sum(
                1
                for j in self.jobs.values()
                if j["status"] == "queued" and j.get("delivered", True)
            )
            limit = 4 if "launcher-overshoot" in self.faults else 3
            starts = min(queued - unclaimed, limit - len(workers))
            if "launcher-respawn" in self.faults:  # an idle respawn: starts with nothing queued
                starts = max(starts, 1 if len(workers) < limit else 0)
            for _ in range(max(0, starts)):
                arn = f"arn:aws:ecs:{REGION}:{ACCOUNT}:task/{self.env}/{uuid.uuid4().hex[:16]}"
                self.tasks[arn] = {
                    "arn": arn,
                    "kind": "worker",
                    "created_at": at,
                    "started_at": at + self.start,
                    "stopped_at": None,
                    "busy": None,
                    "idle_since": at + self.start,
                    "interrupted": False,
                    "script_seconds": 30,
                    "cpu": "2048",
                    "memory": "4096",
                    "definition": f"arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/"
                    f"{self.env}-worker:1",
                }

    def tick_lambda(self, now):
        """Complete running invocations, then start queued jobs while the mapping is enabled."""
        uuid_ = str(uuid.uuid5(uuid.NAMESPACE_URL, "ProcessingShortEncoder"))
        for job in self.jobs.values():
            if job.get("lambda") and job["status"] == "processing" and now >= job["finish_at"]:
                job["status"] = "done"
        if self.plan.mappings.get(uuid_) != "Enabled":
            return
        running = sum(
            1 for j in self.jobs.values() if j.get("lambda") and j["status"] == "processing"
        )
        for job in sorted(
            (j for j in self.jobs.values() if j["status"] == "queued" and j.get("delivered", True)),
            key=lambda j: j["queued_at"],
        ):
            if running >= 2:
                break
            cold = self.last_invocation is None or now - self.last_invocation > 600
            seconds = self.lambda_seconds[0 if cold else 1]
            job.update(status="processing", **{"lambda": True}, finish_at=now + seconds)
            request = uuid.uuid4().hex[:16]
            self.invocations.append(
                {"job": job["pid"], "request": request, "cold": cold, "at": now, "seconds": seconds}
            )
            self.last_invocation = now + seconds
            running += 1

    def task_view(self, task):
        now = self.clock.t
        stopped = task["stopped_at"] is not None and now >= task["stopped_at"]
        status = (
            "STOPPED" if stopped else ("RUNNING" if now >= task["started_at"] else "PROVISIONING")
        )
        view = {
            "taskArn": task["arn"],
            "taskDefinitionArn": task["definition"],
            "lastStatus": status,
            "cpu": task["cpu"],
            "memory": task["memory"],
            "createdAt": iso(self.wall_of(task["created_at"])),
            "pullStartedAt": iso(self.wall_of(task["created_at"] + 2)),
            "containers": [
                {
                    "name": "migration" if task["kind"] == "vpcread" else "worker",
                    "exitCode": task.get("exit", 0) if stopped else None,
                    "imageDigest": "sha256:" + "ab" * 32,
                }
            ],
        }
        if status != "PROVISIONING":
            view["startedAt"] = iso(self.wall_of(task["started_at"]))
        if stopped:
            view.update(
                stoppedAt=iso(self.wall_of(task["stopped_at"])),
                stopCode="UserInitiated" if task.get("interrupted") else "EssentialContainerExited",
            )
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
        env = {
            e["name"]: e["value"]
            for c in payload.get("overrides", {}).get("containerOverrides", [])
            for e in c.get("environment", [])
        }
        spec = self.definitions.get(definition, {})
        kind = "worker"
        if "DC2_MODE" in env:
            kind = "vpcread"
        elif "DC2_SCRIPT" in env or "DC2_SCRIPT" in json.dumps(spec):
            kind = "generator" if "DC2_BASE_URL" in json.dumps(spec) else "probe"
        now = self.clock.t
        task = {
            "arn": arn,
            "definition": definition,
            "kind": kind,
            "created_at": now,
            "started_at": now + self.start,
            "stopped_at": None,
            "busy": None,
            "idle_since": now + self.start,
            "interrupted": False,
            "script_seconds": 30,
            "cpu": payload.get("overrides", {}).get("cpu", spec.get("cpu", "2048")),
            "memory": payload.get("overrides", {}).get("memory", spec.get("memory", "4096")),
        }
        if kind == "worker":
            self.workers_started += 1
            if self.workers_started <= self.dud_encoders:
                task.update(dud=True, stopped_at=now + self.start + 3.0)
        if kind == "generator":
            task["script_seconds"] = 330
            self.logs[("/dc2/tasks", f"generator/generator/{arn.rsplit('/', 1)[-1]}")] = (
                self.generator_lines
            )  # computed on first read: it replays 5 minutes of load
        elif kind == "probe":
            self.logs[("/dc2/tasks", f"Worker/worker/{arn.rsplit('/', 1)[-1]}")] = (
                self.probe_lines()
            )
        elif kind == "vpcread":
            self.start_vpc_read(task, env, definition)
        self.tasks[arn] = task
        return {"tasks": [{"taskArn": arn}], "failures": []}

    def start_vpc_read(self, task, env, definition):
        """The probe's run, as the log line it would print and how long it would take."""
        owner, mode = env["DC2_OWNER"], env["DC2_MODE"]
        self.vpc_reads.append((owner, mode, definition))
        result = {
            "ok": True,
            "mode": mode,
            "owner": owner,
            "connect_attempts": 1,
            "connect_seconds": 1.2,
            "tls": {"verified": True, "server_reports_ssl": True, "protocol": "TLSv1.3"},
        }
        if mode == "schema":
            result.update(heads=1, revision=self.schema[owner])
        else:
            result.update(counts=dict(self.attempt_counts), unknown_states=[])
        task["script_seconds"] = 20
        if "read-slow-resume" in self.faults:  # a paused Aurora: the probe retries for ~2 minutes
            task["script_seconds"] = 140
            result.update(connect_attempts=27, connect_seconds=135.0)
        if "read-hang" in self.faults:  # a task that never stops on its own
            task["script_seconds"] = 100_000
        if "read-tls-unverified" in self.faults:
            result["tls"] = {"verified": False, "server_reports_ssl": False, "protocol": None}
        if "read-two-heads" in self.faults:
            result.update(heads=2, revision=None)
        if "read-db-unreachable" in self.faults:
            result = {"ok": False, "mode": mode, "owner": owner, "error": "TimeoutError"}
            task.update(script_seconds=160, exit=1)
        prefix = f"{owner.title()}Migration"
        lines = ["start", f"DC2-VPC-READ {json.dumps(result)}"]
        stream = task["arn"].rsplit("/", 1)[-1]
        self.logs[("/dc2/tasks", f"{prefix}/migration/{stream}")] = (
            [] if "read-no-log" in self.faults else lines
        )

    def ecs_describe_tasks(self, payload):
        return {
            "tasks": [self.task_view(self.tasks[a]) for a in payload["tasks"] if a in self.tasks],
            "failures": [],
        }

    def ecs_list_tasks(self, payload):
        want = payload.get("desiredStatus", "RUNNING")
        return {
            "taskArns": [
                a
                for a, t in self.tasks.items()
                if (self.task_view(t)["lastStatus"] == "STOPPED") == (want == "STOPPED")
            ]
        }

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
        arn = payload["taskDefinition"]
        if "migration" in arn:
            owner = "media" if "mediamigration" in arn else "processing"
            return {
                "taskDefinition": {
                    "taskDefinitionArn": arn,
                    "family": f"{self.env}-{owner}migration",
                    "cpu": "256",
                    "memory": "512",
                    "executionRoleArn": f"arn:aws:iam::{ACCOUNT}:role/{self.env}-{owner}-exec",
                    "taskRoleArn": f"arn:aws:iam::{ACCOUNT}:role/{self.env}-{owner}-migration",
                    "networkMode": "awsvpc",
                    "requiresCompatibilities": ["FARGATE"],
                    "runtimePlatform": {
                        "cpuArchitecture": "X86_64",
                        "operatingSystemFamily": "LINUX",
                    },
                    "containerDefinitions": [
                        {
                            "name": "migration",
                            "image": f"{self.repository(owner)}@{self.stack_digests[owner]}",
                            "logConfiguration": {
                                "logDriver": "awslogs",
                                "options": {
                                    "awslogs-group": group,
                                    "awslogs-region": REGION,
                                    "awslogs-stream-prefix": f"{owner.title()}Migration",
                                },
                            },
                        }
                    ],
                }
            }
        return {
            "taskDefinition": {
                "taskDefinitionArn": payload["taskDefinition"],
                "family": f"{self.env}-worker",
                "cpu": "2048",
                "memory": "4096",
                "executionRoleArn": f"arn:aws:iam::{ACCOUNT}:role/{self.env}-exec",
                "taskRoleArn": f"arn:aws:iam::{ACCOUNT}:role/{self.env}-worker",
                "networkMode": "awsvpc",
                "requiresCompatibilities": ["FARGATE"],
                "runtimePlatform": {"cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX"},
                "containerDefinitions": [
                    {
                        "name": "worker",
                        "image": f"{self.repository('worker')}@{self.stack_digests['worker']}",
                        "logConfiguration": {
                            "logDriver": "awslogs",
                            "options": {
                                "awslogs-group": group,
                                "awslogs-region": REGION,
                                "awslogs-stream-prefix": "Worker",
                            },
                        },
                    }
                ],
            }
        }

    def ecs_register_task_definition(self, payload):
        self.registered += 1
        # A deployed family already holds revision 1 (CloudFormation made it).
        deployed = payload["family"].endswith(("migration", "-worker"))
        revision = self.registered + (1 if deployed else 0)
        family = f"task-definition/{payload['family']}:{revision}"
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
        return {
            "events": [{"timestamp": 0, "message": m} for m in lines],
            "nextForwardToken": "end",
        }

    def logs_filter_log_events(self, payload):
        """The encoder's own line and Lambda's REPORT line for each simulated invocation."""
        events = []
        for call in self.invocations:
            if "REPORT" in payload.get("filterPattern", ""):
                init = f"\tInit Duration: {call['seconds'] * 100:.2f} ms" if call["cold"] else ""
                events.append(
                    {
                        "message": (
                            f"REPORT RequestId: {call['request']}"
                            f"\tDuration: {call['seconds'] * 1000:.2f} ms"
                            f"\tBilled Duration: {int(call['seconds'] * 1000) + 1} ms"
                            f"\tMemory Size: "
                            f"3584 MB\tMax Memory Used: 410 MB{init}"
                        )
                    }
                )
            else:
                line = {
                    "event": "short_encode",
                    "outcome": "finished",
                    "cold": call["cold"],
                    "job_id": call["job"],
                    "request_id": call["request"],
                    "seconds": call["seconds"],
                }
                events.append({"message": "dc2.short_encode " + json.dumps(line)})
        return {"events": events}

    def ecr_describe_images(self, payload):
        name, tag = payload["repositoryName"], payload["imageIds"][0]["imageTag"]
        digest = self.image_digest(self.repository_of(name), tag)
        return {"imageDetails": [{"imageDigest": digest, "imageTags": [tag]}]}

    def ecr_batch_get_image(self, payload):
        digest = payload["imageIds"][0]["imageDigest"]
        if digest not in self.manifests:
            return {"images": [], "failures": [{"failureCode": "ImageNotFound"}]}
        return {
            "images": [
                {"imageId": {"imageDigest": digest}, "imageManifest": self.manifests[digest]}
            ]
        }

    def repository_of(self, name):
        return f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{name}"

    def ecr_describe_image_scan_findings(self, payload):
        counts = {"MEDIUM": 2}
        if "scan-high" in self.faults:
            counts["HIGH"] = 1
        status = "IN_PROGRESS" if "scan-pending" in self.faults else "COMPLETE"
        if self.scan_findings is None:
            return {
                "imageId": payload["imageId"],
                "imageScanStatus": {"status": status},
                "imageScanFindings": {"findingSeverityCounts": counts},
            }
        counts = {}
        for _, severity in self.scan_findings:
            counts[severity] = counts.get(severity, 0) + 1
        start = int(payload.get("nextToken") or 0)
        end = start + self.scan_page
        reply = {
            "imageId": payload["imageId"],
            "imageScanStatus": {"status": status},
            "imageScanFindings": {
                "findingSeverityCounts": counts,
                "findings": [
                    {"name": n, "severity": sev} for n, sev in self.scan_findings[start:end]
                ],
            },
        }
        if end < len(self.scan_findings):
            reply["nextToken"] = str(end)
        return reply

    def s3api_list_object_versions(self, payload):
        job = payload["Prefix"].split("/")[1]
        done = any(j["pid"] == job and j["status"] == "done" for j in self.jobs.values())
        key = f"{payload['Prefix']}{uuid.uuid5(uuid.NAMESPACE_URL, job)}/primary.mp4"
        return {"Versions": [{"Key": key, "VersionId": "v1"}] if done else [], "IsTruncated": False}

    def probe_lines(self):
        result = {
            "own_database": "connected",
            "own_ddl": "denied:InsufficientPrivilegeError",
            "other_database": "connect-denied:InvalidAuthorizationSpecificationError",
            "other_database_read": None,
        }
        if "crossdb-open" in self.faults:
            result.update(
                own_ddl="ALLOWED", other_database="reached", other_database_read="ALLOWED"
            )
        if "db-unreachable" in self.faults:
            result = {"own_database": "connect-denied:TimeoutError"}
        return ["start", "DC2-RESULT " + json.dumps(result)]

    def generator_lines(self):
        """Run the real generator against a latency model on its own virtual clock."""
        clock, world = VirtualClock(), self
        seen = {}

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
            seen[path] = seen.get(path, 0) + 1
            # every 10th call per path, not a hash of the random user: 20 logins always see two
            if "throttled" in world.faults and seen[path] % 10 == 0:
                status = 429  # the Gateway's own throttle, not the application
            return status, ms, cookies, b""

        sink = io.StringIO()
        with contextlib.redirect_stdout(sink):
            generator.run(
                {"users": 50, "seconds": 180, "warmup": 5, "other_seconds": 20, "logins": 20},
                request,
                clock.monotonic,
                clock.sleep,
                generator.emit,
            )
        return sink.getvalue().splitlines()

    def capacity_at(self, minute, cluster=None):
        """0.5 ACU for 5.5 minutes after the database was last used, otherwise paused at 0."""
        if "never-pauses" in self.faults:
            return 0.5
        moment = self.clock.t0 + (minute - EPOCH)
        if self.database and cluster:
            return 0.5 if self.awake(cluster, moment) else 0.0
        used = self.last_use
        return 0.5 if used is not None and used <= moment < used + 330 else 0.0

    def cloudwatch_get_metric_statistics(self, payload):
        start, end = int(parse_epoch(payload["StartTime"])), int(parse_epoch(payload["EndTime"]))
        now = self.clock.wall()
        points = []
        dimensions = payload.get("Dimensions") or [{}]
        cluster = dimensions[0].get("Value")
        for minute in range(start - start % 60 + 60, end, 60):
            if minute <= now:
                value = self.capacity_at(minute, cluster)
                points.append(
                    {"Timestamp": iso(minute), "Minimum": value, "Maximum": value, "Average": value}
                )
        return {"Datapoints": points, "Label": "ServerlessDatabaseCapacity"}

    def rds_describe_db_clusters(self, payload):
        return {
            "DBClusters": [
                {
                    "ServerlessV2ScalingConfiguration": {
                        "MinCapacity": 0.0,
                        "MaxCapacity": self.max_acu,
                        "SecondsUntilAutoPause": self.auto_pause_seconds,
                    }
                }
            ]
        }

    def ce_get_cost_and_usage(self, payload):
        groups = {
            "Amazon Relational Database Service": "1.62",
            "Amazon Elastic Container Service": "0.41",
            "AWS Lambda": "0.03",
            "Amazon CloudFront": "0.0",
            "Amazon Simple Storage Service": "0.02",
            "EC2 - Other": "0.11",
            "Amazon Simple Queue Service": "0.0",
            "AWS Secrets Manager": "0.2",
        }
        return {
            "ResultsByTime": [
                {
                    "Estimated": True,
                    "Groups": [
                        {"Keys": [k], "Metrics": {"UnblendedCost": {"Amount": v, "Unit": "USD"}}}
                        for k, v in groups.items()
                    ],
                }
            ]
        }


def parse_epoch(text):
    from scripts.aws.v1.proof.core import parse_time

    return parse_time(text).timestamp()


def build(args, *, session="open", world=None, sql=True, tmp=None, unattended=False):
    """A simulated Context over real private files in a throwaway state directory."""
    import tempfile

    world = world or SimWorld()
    folder = Path(tmp or tempfile.mkdtemp(prefix="dc2-proof-sim-"))
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder.chmod(0o700)
    (folder / "session").mkdir(mode=0o700, exist_ok=True)
    outputs = world.outputs()
    (folder / "outputs.json").write_text(json.dumps(outputs))
    config = {
        "operator_station": "sim-station",
        "environment_id": world.env,
        "journal": str(folder / "session" / "journal.json"),
        "outputs_file": str(folder / "outputs.json"),
        "edge_open": dict(EDGE_OPEN),
    }
    if sql:
        config["sql"] = {
            "ca_file": "/dev/null",
            "media_dsn_file": "/dev/null",
            "processing_dsn_file": "/dev/null",
        }
    (folder / "operator-config.json").write_text(json.dumps(config))
    creds = folder / "smoke-credentials.json"
    creds.write_text(json.dumps({"email": "smoke@example.com", "password": "sim-password"}))
    creds.chmod(0o600)
    world.users["smoke@example.com"] = {"id": "smoke-user", "password": "sim-password"}
    data, cfg, hooks, urls, outputs, journal = load_state(folder)
    deploy_journal = DeployJournal(
        folder / "deploy-journal.json", station="sim-station", environment=world.env
    )
    deploy_journal.create(
        {
            "run_id": "sim",
            "env": world.env,
            "steps": {},
            "outputs": world.journal_outputs(),
            "images": world.journal_images(),
            "events": [],
            "resources": world.journal_resources(),
        }
    )
    journal.initialize(verified_empty=True, exclusive_station=True)
    if session != "closed":
        with journal.locked() as state:
            state.update(session=session, paused=False, unattended=unattended)
            journal.save(state)
        world.plan.stage = dict(OPEN_EDGE)
    if session == "open":  # what a full `session open` leaves enabled
        for handler in operations.MAPPINGS:
            world.plan.mappings[str(uuid.uuid5(uuid.NAMESPACE_URL, handler))] = "Enabled"
        if unattended:
            world.plan.rules[f"{world.env}-ProcessingLauncher-rule"] = "ENABLED"
    return Context(
        scope={"profile": "dc2-project2-mfa", "region": REGION, "account": ACCOUNT},
        state_dir=folder,
        run_id=getattr(args, "run_id", "sim"),
        simulated=True,
        outputs=outputs,
        config=cfg,
        hooks=hooks,
        urls=urls,
        data=data,
        journal=journal,
        aws=world,
        http=world.http,
        clock=world.clock.monotonic,
        sleep=world.clock.sleep,
        wall=world.clock.wall,
        credentials=lambda: json.loads(creds.read_text()),
        sqs=lambda: FakeSqs(world),
        sdk=lambda scope: world,
        release_main=release_cli.main,
        world=world,
    )


def reopen(ctx, session):
    """What `session open` leaves behind in the simulated account, between two harness runs."""
    with ctx.journal.locked() as state:
        state.update(session=session, paused=False)
        ctx.journal.save(state)
    ctx.world.plan.stage = dict(OPEN_EDGE)


def opt_in_launcher(ctx):
    """What `session close` then `session open --unattended` leave behind on a stack that has
    the launcher: the SQL flag on and the rule enabled."""
    with ctx.journal.locked() as state:
        state.update(unattended=True)
        ctx.journal.save(state)
    ctx.world.plan.rules[f"{ctx.world.env}-ProcessingLauncher-rule"] = "ENABLED"


def build_evidence(path, *, source_sha, config_ids=None, failures=()):
    """A build_and_verify evidence file for the three images, as `deploy/v1` would write it."""
    config_ids = config_ids or LOCAL_ID
    images = {
        owner: {
            "tag": f"dc2-v1-{owner}:local-{source_sha[:12]}",
            "build_exit_code": 0,
            "config_id": config_ids[owner],
            "source_sha": source_sha,
            "runtime_contents": {"ffmpeg": owner == "worker", "redis": False, "rq": False},
        }
        for owner in ("media", "processing", "worker")
    }
    for image in images.values():
        image["trivy_scan"] = scan_receipt(
            json.dumps(
                {
                    "Metadata": {"ImageID": image["config_id"]},
                    "Results": [
                        {"Class": "os-pkgs", "Type": "debian"},
                        {"Class": "lang-pkgs", "Type": "python-pkg"},
                    ],
                }
            ).encode(),
            config_id=image["config_id"],
            source_sha=source_sha,
        )
    Path(path).write_text(
        json.dumps(
            {
                "status": "LOCAL_ARTIFACT_FAIL" if failures else "LOCAL_ARTIFACT_PASS",
                "source_sha": source_sha,
                "images": images,
                "failures": list(failures),
            }
        )
    )
    return Path(path)
