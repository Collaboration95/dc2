import copy

import pytest

from scripts.aws.journal import Journal

OLD = "sha256:" + "1" * 64
NEW = "sha256:" + "2" * 64


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def sleep(self, value):
        self.now += value


class Fake:
    def __init__(self, config):
        self.config = config
        self.calls = []
        self.tasks = {}
        self.definitions = {}
        self.services = {}
        self.bad = False
        self.lost = False
        self.partial = False
        self.stopping = False
        self.stale_list = False
        self.reverted = False
        self.next = 0
        self.tokens = {}
        self.instances = {
            "state": {
                "InstanceId": "state",
                "State": {"Name": "running"},
                "PublicDnsName": "fresh.example",
                "PublicIpAddress": "192.0.2.1",
            }
        }
        self.volumes = {}
        self.addresses = []
        self.distribution = {
            "Origins": {
                "Items": [
                    {
                        "Id": "state-origin",
                        "DomainName": "old.example",
                        "CustomOriginConfig": {"OriginProtocolPolicy": "http-only"},
                        "CustomHeaders": {
                            "Quantity": 1,
                            "Items": [{"HeaderName": "X-Origin", "HeaderValue": "PRIVATE-DUMMY"}],
                        },
                    }
                ]
            },
            "ViewerCertificate": {"CloudFrontDefaultCertificate": True},
        }
        for key, ref in config["task_definitions"].items():
            for candidate in (ref, ref.replace(":1", ":2")):
                dg = NEW if candidate.endswith(":2") else OLD
                names = ["media", "reconciler"] if key == "media" else [key]
                self.definitions[candidate] = {
                    "containerDefinitions": [
                        {"name": name, "image": "repo@" + dg, "essential": True, "stopTimeout": 120}
                        for name in names
                    ]
                }
        for key, name in config["services"].items():
            ref = config["task_definitions"][key]
            self.services[name] = {
                "serviceName": name,
                "taskDefinition": ref,
                "desiredCount": 1,
                "runningCount": 1,
                "pendingCount": 0,
                "deployments": [{"taskDefinition": ref, "runningCount": 1, "pendingCount": 0}],
            }
            self.add_task(ref, group="service:" + name)

    def add_task(self, ref, *, group="", status="RUNNING", exit_code=None):
        self.next += 1
        arn = "task-" + str(self.next)
        task = {
            "taskArn": arn,
            "taskDefinitionArn": ref,
            "group": group,
            "lastStatus": status,
            "containers": [
                {
                    "name": c["name"],
                    "imageDigest": c["image"].split("@")[1],
                    **({"exitCode": exit_code} if exit_code is not None else {}),
                }
                for c in self.definitions[ref]["containerDefinitions"]
            ],
        }
        self.tasks[arn] = task
        return arn

    def call(self, service, operation, payload, *, deadline=None):
        self.calls.append((service, operation, copy.deepcopy(payload), deadline))
        if operation == "list-tasks":
            if self.stale_list:
                return {"taskArns": []}
            # Deliberately paginate into one-item pages. Includes STOPPING with desired STOPPED.
            wanted = [
                a
                for a, t in self.tasks.items()
                if (t["lastStatus"] in {"STOPPING", "STOPPED"})
                == (payload["desiredStatus"] == "STOPPED")
            ]
            offset = int(payload.get("nextToken", "0"))
            return {
                "taskArns": wanted[offset : offset + 1],
                **({"nextToken": str(offset + 1)} if offset + 1 < len(wanted) else {}),
            }
        if operation == "describe-tasks":
            return {
                "tasks": [copy.deepcopy(self.tasks[a]) for a in payload["tasks"] if a in self.tasks]
            }
        if operation == "run-task":
            token = payload["clientToken"]
            if token not in self.tokens:
                ref = payload["taskDefinition"]
                migration = "migration" in ref
                self.tokens[token] = self.add_task(
                    ref,
                    status="STOPPED" if migration else "RUNNING",
                    exit_code=0 if migration else None,
                )
            if self.lost:
                self.lost = False
                raise TimeoutError("PRIVATE-DUMMY must never be persisted")
            if self.partial:
                return {"tasks": [], "failures": [{"reason": "capacity"}]}
            return {"tasks": [copy.deepcopy(self.tasks[self.tokens[token]])]}
        if operation == "stop-task":
            self.tasks[payload["task"]]["lastStatus"] = "STOPPING" if self.stopping else "STOPPED"
            return {"task": copy.deepcopy(self.tasks[payload["task"]])}
        if operation == "describe-services":
            return {"services": [copy.deepcopy(self.services[n]) for n in payload["services"]]}
        if operation == "describe-task-definition":
            return {"taskDefinition": copy.deepcopy(self.definitions[payload["taskDefinition"]])}
        if operation == "update-service":
            name = payload["service"]
            s = self.services[name]
            ref = payload.get("taskDefinition", s["taskDefinition"])
            count = payload["desiredCount"]
            for t in self.tasks.values():
                if t.get("group") == "service:" + name and t["lastStatus"] != "STOPPED":
                    t["lastStatus"] = "STOPPING" if self.stopping else "STOPPED"
            if count:
                status = "STOPPED" if self.bad and ref.endswith(":2") else "RUNNING"
                self.add_task(
                    ref,
                    group="service:" + name,
                    status=status,
                    exit_code=42 if status == "STOPPED" else None,
                )
            s.update(
                taskDefinition=ref,
                desiredCount=count,
                runningCount=count,
                pendingCount=0,
                deployments=[{"taskDefinition": ref, "runningCount": count, "pendingCount": 0}],
            )
            return {"service": copy.deepcopy(s)}
        if operation == "describe-instances":
            return {"Reservations": [{"Instances": list(copy.deepcopy(self.instances).values())}]}
        if operation == "start-instances":
            self.instances["state"].update(
                State={"Name": "running"}, PublicDnsName="new.example", PublicIpAddress="192.0.2.2"
            )
            return {}
        if operation == "stop-instances":
            self.instances["state"].update(State={"Name": "stopped"})
            self.instances["state"].pop("PublicDnsName", None)
            self.instances["state"].pop("PublicIpAddress", None)
            return {}
        if operation == "terminate-instances":
            for i in payload["InstanceIds"]:
                self.instances[i]["State"]["Name"] = "terminated"
            return {}
        if operation == "describe-volumes":
            return {"Volumes": list(self.volumes.values())}
        if operation == "delete-volume":
            self.volumes.pop(payload["VolumeId"])
            return {}
        if operation == "describe-addresses":
            return {"Addresses": copy.deepcopy(self.addresses)}
        if operation == "get-distribution-config":
            return {"ETag": "etag-1", "DistributionConfig": copy.deepcopy(self.distribution)}
        if operation == "update-distribution":
            assert payload["IfMatch"] == "etag-1"
            self.distribution = copy.deepcopy(payload["DistributionConfig"])
            return {}
        if operation == "get-distribution":
            return {"Distribution": {"Status": "Deployed"}}
        raise AssertionError((service, operation))


@pytest.fixture
def config():
    return {
        "mode": "plan",
        "region": "ap-southeast-1",
        "environment_id": "demo",
        "operator_station": "station-a",
        "cluster": "dedicated-demo",
        "max_worker_tasks": 3,
        "worker_lifetime_seconds": 900,
        "session_end_epoch": 2000,
        "services": {
            "media": "media-service",
            "processing_api": "api-service",
            "processing_recovery": "recovery-service",
        },
        "task_definitions": {
            k: k.replace("_", "-") + ":1"
            for k in (
                "media",
                "processing_api",
                "processing_recovery",
                "worker",
                "media_migration",
                "processing_migration",
            )
        },
        "network": {
            "subnets": ["subnet"],
            "security_groups": ["sg"],
            "assign_public_ip": "ENABLED",
        },
        "state_instance_id": "state",
        "cloudfront_distribution_id": "distribution",
        "public_url": "https://demo.cloudfront.net",
        "origin_transport_accepted": True,
    }


@pytest.fixture
def fake(config):
    return Fake(config)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def journal(tmp_path):
    folder = tmp_path / "private"
    folder.mkdir(mode=0o700)
    journal = Journal(folder / "journal.json", station="station-a", environment="demo")
    journal.initialize(verified_empty=True, exclusive_station=True)
    with journal.locked() as state:
        state.update(paused=False, session="open")
        journal.save(state)
    return journal


def artifact(owner, dg):
    config = "sha256:" + ("a" if dg == OLD else "b") * 64
    source = "c" * 40
    receipt = {"status": "PASS", "config_id": config, "source_sha": source}
    return {
        "owner": owner,
        "platform": "linux/amd64",
        "source_sha": source,
        "config_id": config,
        "manifest_digest": dg,
        "manifest_config_id": config,
        "tests": {**receipt, "passed": 12},
        "artifact_test": {**receipt, "kind": "offline image imports"},
        "scan": {**receipt, "report_sha256": "sha256:" + "e" * 64, "fixable_high_critical": 0},
    }
