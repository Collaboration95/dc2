"""Offline stand-in for AWS used by `deploy --dry-run`, `rehearse` and the tests.

It answers exactly the allowlisted calls the pipeline makes, with enough state (stacks, change
sets, buckets with versions, repositories, parameters, tasks, Aurora) that the real ordering
logic runs unchanged: a database that still exists makes the stack deletion fail, a bucket
with versions cannot be deleted, immutable tags reject a second push, and so on. Asynchronous
operations take one polling round to finish so the wait loops are exercised too.

Nothing here touches the network. A dry run therefore proves ordering and request shape; it
does not prove any fact about the real account.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import uuid
from pathlib import Path

from scripts.aws.v1.deploy import PROJECT_KEY, RUN_KEY, AwsError, check_operation, redact
from scripts.aws.v1.operations import HANDLERS, QUEUES
from scripts.aws.v1_operator import sanitized_environment

RETAINED = {"AWS::S3::Bucket", "AWS::ECR::Repository", "AWS::RDS::DBCluster",
            "AWS::RDS::DBInstance"}
LEGACY = "dc2-v1-20261015t1146-bootstrap"


def short(*parts):
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:8]


def tags_of(pairs):
    return {t["Key"]: t["Value"] for t in pairs}


class SimulatedAws:
    simulated = True

    def __init__(self, settings, seed=None):
        self.s = settings
        self.calls, self.fail = [], {}
        self.mtd, self.forecast, self.mfa, self.fargate_vcpus = 0.0, 0.0, True, 6.0
        self.budget_limit, self.budget_name = 30.0, settings.budget_name
        self.engine_available = True
        self.stacks, self.objects, self.buckets, self.repos = {}, {}, {}, {}
        self.params, self.param_values, self.groups = {}, {}, {}
        self.clusters, self.instances, self.snapshots, self.tasks = {}, {}, {}, {}
        self.task_exit = {}  # task-definition substring -> exit code
        self.pending, self.puts, self.invalidations = {}, [], {}
        self.role_passwords = None  # the passwords the database holds after the last bootstrap
        self.version_seq = 0
        self.stop_lag = 0  # describe-tasks rounds a stopped task keeps reporting RUNNING
        # The previous sprint's rolled-back staging stack, so the plan shows it left alone.
        self.stacks[LEGACY] = {"status": "ROLLBACK_COMPLETE", "tags": {}, "resources": [],
                               "outputs": {}, "changesets": {}, "id": "legacy"}
        if seed:
            self.seed(seed)

    # ---- dispatch ---------------------------------------------------------------------
    def call(self, service, operation, payload, *, deadline=None):
        check_operation(service, operation, payload)
        self.calls.append((service, operation, redact(service, operation, payload)))
        injected = self.fail.get((service, operation))
        if injected:
            if isinstance(injected, list):
                injected = injected.pop(0) if injected else None
            if injected:
                raise injected
        handler = getattr(self, f"{service}_{operation}".replace("-", "_"))
        return handler(payload)

    def error(self, service, operation, code, hint=""):
        return AwsError(service, operation, code, hint)

    # ---- account facts (clearly simulated) ----------------------------------------------
    def sts_get_caller_identity(self, payload):
        return {"Account": self.s.account, "Arn": f"arn:aws:iam::{self.s.account}:user/simulated"}

    def iam_list_mfa_devices(self, payload):
        return {"MFADevices": [{"SerialNumber": "simulated"}] if self.mfa else []}

    def lambda_get_account_settings(self, payload):
        return {"AccountLimit": {"ConcurrentExecutions": 10, "UnreservedConcurrentExecutions": 10}}

    def service_quotas_get_service_quota(self, payload):
        return {"Quota": {"Value": self.fargate_vcpus}}

    def rds_describe_db_engine_versions(self, payload):
        if not self.engine_available:
            return {"DBEngineVersions": []}
        return {"DBEngineVersions": [{"EngineVersion": payload["EngineVersion"],
                                      "ServerlessV2FeaturesSupport": {
                                          "MinCapacity": 0.0, "MaxCapacity": 256.0}}]}

    def budgets_describe_budgets(self, payload):
        return {"Budgets": [{"BudgetName": self.budget_name, "TimeUnit": "MONTHLY",
                             "BudgetLimit": {"Amount": str(self.budget_limit), "Unit": "USD"}}]}

    def ce_get_cost_and_usage(self, payload):
        return {"ResultsByTime": [{"Total": {"UnblendedCost": {"Amount": str(self.mtd),
                                                               "Unit": "USD"}}}]}

    def ce_get_cost_forecast(self, payload):
        if self.forecast is None:
            raise self.error("ce", "get-cost-forecast", "DataUnavailableException")
        return {"Total": {"Amount": str(self.forecast), "Unit": "USD"}}

    # ---- CloudFormation ------------------------------------------------------------------
    def view(self, name):
        stack = self.stacks[name]
        return {"StackName": name, "StackId": stack["id"], "StackStatus": stack["status"],
                "Tags": [{"Key": k, "Value": v} for k, v in stack["tags"].items()],
                "Outputs": [{"OutputKey": k, "OutputValue": v}
                            for k, v in stack["outputs"].items()]}

    def cloudformation_describe_stacks(self, payload):
        name = payload["StackName"]
        if name in self.pending:  # one polling round reports IN_PROGRESS, the next the result
            entry = self.pending[name]
            if entry[0] > 0:
                entry[0] -= 1
            else:
                del self.pending[name]
                entry[1]()
        stack = self.stacks.get(name)
        if stack is None or stack["status"] == "DELETE_COMPLETE":
            raise self.error("cloudformation", "describe-stacks", "ValidationError",
                             f"Stack with id {name} does not exist")
        return {"Stacks": [self.view(name)]}

    def template_of(self, request):
        if "TemplateBody" in request:
            return json.loads(request["TemplateBody"])
        key = request["TemplateURL"].split(".amazonaws.com/", 1)[1]
        return json.loads(self.objects[key])

    @staticmethod
    def included(template, parameters):
        apps = parameters.get("DeployApplications", "false") == "true"
        return {name: res for name, res in template["Resources"].items()
                if res.get("Condition") != "Applications" or apps}

    def cloudformation_create_change_set(self, request):
        name, kind = request["StackName"], request["ChangeSetType"]
        template = self.template_of(request)
        parameters = {p["ParameterKey"]: p["ParameterValue"] for p in request["Parameters"]}
        stack = self.stacks.get(name)
        if kind == "CREATE":
            if stack and stack["status"] != "REVIEW_IN_PROGRESS":
                raise self.error("cloudformation", "create-change-set", "AlreadyExistsException")
            stack = self.stacks[name] = {
                "status": "REVIEW_IN_PROGRESS", "id": f"id-{short(name)}",
                "tags": tags_of(request["Tags"]), "resources": [], "outputs": {},
                "changesets": {}, "template": None}
        elif stack is None:
            raise self.error("cloudformation", "create-change-set", "ValidationError")
        previous = set(self.included(stack["template"], stack["parameters"])) \
            if stack.get("template") else set()
        wanted = self.included(template, parameters)
        changes = [{"ResourceChange": {"Action": "Add", "LogicalResourceId": logical,
                                       "ResourceType": res["Type"], "Replacement": "False"}}
                   for logical, res in wanted.items() if logical not in previous]
        stack["changesets"][request["ChangeSetName"]] = {
            "Status": "CREATE_COMPLETE" if changes else "FAILED",
            "StatusReason": "" if changes else "The submitted information didn't contain changes.",
            "ExecutionStatus": "AVAILABLE" if changes else "UNAVAILABLE", "Changes": changes,
            "template": template, "parameters": parameters, "kind": kind}
        return {"Id": f"cs-{short(name, request['ChangeSetName'])}", "StackId": stack["id"]}

    def cloudformation_describe_change_set(self, payload):
        stack = self.stacks.get(payload["StackName"])
        found = (stack or {}).get("changesets", {}).get(payload["ChangeSetName"])
        if found is None:
            raise self.error("cloudformation", "describe-change-set", "ChangeSetNotFound")
        return {key: found[key] for key in ("Status", "StatusReason", "ExecutionStatus", "Changes")}

    def cloudformation_execute_change_set(self, payload):
        name = payload["StackName"]
        stack = self.stacks[name]
        change_set = stack["changesets"][payload["ChangeSetName"]]
        if change_set["ExecutionStatus"] != "AVAILABLE":
            raise self.error("cloudformation", "execute-change-set", "InvalidChangeSetStatus")
        change_set["ExecutionStatus"] = "EXECUTE_COMPLETE"
        stack["status"] = "CREATE_IN_PROGRESS" if change_set["kind"] == "CREATE" \
            else "UPDATE_IN_PROGRESS"
        failure = self.fail.get(("stack-complete", name))
        self.pending[name] = [1, lambda: self.complete_stack(name, change_set, failure)]
        return {}

    def complete_stack(self, name, change_set, failure=None):
        stack = self.stacks[name]
        stack["template"], stack["parameters"] = change_set["template"], change_set["parameters"]
        if failure:
            stack["status"] = "ROLLBACK_COMPLETE"
            stack["events"] = [{"LogicalResourceId": "Simulated", "ResourceStatus": "CREATE_FAILED",
                                "ResourceStatusReason": failure}]
            return
        known = {r["logical"] for r in stack["resources"]}
        env = change_set["parameters"].get("EnvironmentId") or change_set["parameters"].get(
            "Namespace", name)
        for logical, res in self.included(change_set["template"], change_set["parameters"]).items():
            if logical not in known:
                stack["resources"].append(self.materialize(name, env, logical, res, stack))
        apps = change_set["parameters"].get("DeployApplications", "false") == "true"
        stack["outputs"] = {
            key: self.output_value(key, name, env, stack)
            for key, out in change_set["template"].get("Outputs", {}).items()
            if out.get("Condition") != "Applications" or apps}
        stack["status"] = "UPDATE_COMPLETE" if change_set["kind"] == "UPDATE" else "CREATE_COMPLETE"

    def materialize(self, stack_name, env, logical, res, stack):
        kind, suffix = res["Type"], short(stack_name, logical)
        physical = f"{logical}-{suffix}"
        tags = dict(stack["tags"])
        if kind == "AWS::S3::Bucket":
            physical = f"{env}-{logical.lower()}-{suffix}"[:63]
            if "BucketName" in res.get("Properties", {}):
                physical = f"{env}-artifacts-{self.s.account}"
            versions = []
            if logical in {"SourceBucket", "OutputBucket"}:  # data a real run would have written
                versions = [{"Key": "uploads/a.mp4", "VersionId": "v1"},
                            {"Key": "uploads/a.mp4", "VersionId": "v2"}]
            self.buckets[physical] = {"tags": tags, "versions": versions,
                                      "markers": [{"Key": "uploads/a.mp4", "VersionId": "dm1"}]
                                      if versions else [], "uploads": []}
        elif kind == "AWS::ECR::Repository":
            physical = f"{stack_name}-{logical.lower()}-{suffix}"
            self.repos[physical] = {"tags": tags, "images": {}}
        elif kind == "AWS::RDS::DBCluster":
            physical = f"{stack_name}-databasecluster-{suffix}"
            self.clusters[physical] = {"status": "available", "protected": True, "tags": tags}
        elif kind == "AWS::RDS::DBInstance":
            physical = f"{stack_name}-databaseinstance-{suffix}"
            self.instances[physical] = {"status": "available", "tags": tags}
        elif kind == "AWS::Logs::LogGroup":
            template = res["Properties"]["LogGroupName"]["Fn::Sub"]
            physical = template.replace("${EnvironmentId}", env)
            self.groups[physical] = tags
        return {"logical": logical, "type": kind, "physical": physical}

    def output_value(self, key, stack_name, env, stack):
        by_logical = {r["logical"]: r["physical"] for r in stack["resources"]}
        account, region = self.s.account, self.s.region
        if key == "ArtifactsBucket":
            return by_logical["Artifacts"]
        if key.endswith("RepositoryUri"):
            return f"{account}.dkr.ecr.{region}.amazonaws.com/{by_logical[key[:-3]]}"
        table = {
            "SourceBucketName": by_logical.get("SourceBucket"),
            "OutputBucketName": by_logical.get("OutputBucket"),
            "FrontendBucketName": by_logical.get("FrontendBucket"),
            "FrontendUrl": "https://d111111abcdef8.cloudfront.net",
            "DistributionId": "E1SIMULATED",
            "VpcId": "vpc-0sim", "PrivateSubnetIds": "subnet-0p1,subnet-0p2",
            "PublicTaskSubnetIds": "subnet-0t1,subnet-0t2",
            "WorkerSecurityGroupId": "sg-0worker", "MigrationSecurityGroupId": "sg-0migrate",
            "DatabaseEndpoint": f"{env}.cluster-sim.{region}.rds.amazonaws.com",
            "BootstrapSecretArn": f"arn:aws:secretsmanager:{region}:{account}:secret:rds!sim",
            "ClusterArn": f"arn:aws:ecs:{region}:{account}:cluster/{env}",
            "HttpApiId": "abc123def4",
            "HttpApiUrl": f"https://abc123def4.execute-api.{region}.amazonaws.com",
        }
        if table.get(key):
            return table[key]
        if key.endswith("TaskDefinitionArn"):
            return f"arn:aws:ecs:{region}:{account}:task-definition/{env}-{key[:-17].lower()}:1"
        if key.endswith("MappingId"):
            return str(uuid.uuid5(uuid.NAMESPACE_URL, key))
        if key.endswith("RuleName"):
            return f"{env}-{key[:-8]}"
        if key.endswith("FunctionName"):
            return f"{env}-{key[:-12]}"
        if key.endswith("AliasArn"):
            return f"arn:aws:lambda:{region}:{account}:function:{env}-{key[:-8]}:live"
        if key.endswith(("QueueUrl", "DlqUrl")):
            return f"https://sqs.{region}.amazonaws.com/{account}/{env}-{key}"
        if key.endswith(("QueueArn", "DlqArn")):
            return f"arn:aws:sqs:{region}:{account}:{env}-{key}"
        return f"simulated-{key}"

    def cloudformation_describe_stack_events(self, payload):
        return {"StackEvents": self.stacks[payload["StackName"]].get("events", [])}

    def cloudformation_describe_stack_resources(self, payload):
        stack = self.stacks[payload["StackName"]]
        return {"StackResources": [
            {"ResourceType": r["type"], "PhysicalResourceId": r["physical"],
             "LogicalResourceId": r["logical"]} for r in stack["resources"]]}

    def cloudformation_delete_stack(self, payload):
        name = payload["StackName"]
        self.stacks[name]["status"] = "DELETE_IN_PROGRESS"
        self.pending[name] = [1, lambda: self.finish_delete(name)]
        return {}

    def finish_delete(self, name):
        stack = self.stacks[name]
        mine = {r["physical"] for r in stack["resources"]}
        if mine & set(self.instances) or mine & set(self.clusters):
            stack["status"] = "DELETE_FAILED"
            stack["events"] = [{"LogicalResourceId": "Subnet", "ResourceStatus": "DELETE_FAILED",
                                "ResourceStatusReason": "The subnet has dependencies"}]
            return
        for resource in stack["resources"]:
            if resource["type"] not in RETAINED:  # Retain resources survive the stack
                self.groups.pop(resource["physical"], None)
        stack["status"] = "DELETE_COMPLETE"

    # ---- S3 -----------------------------------------------------------------------------------
    def s3api_head_bucket(self, payload):
        if payload["Bucket"] not in self.buckets:
            raise self.error("s3api", "head-bucket", "404")
        return {}

    def s3api_put_object(self, payload):
        key = payload["Key"]
        data = Path(payload["Body"]).read_bytes()  # frontend assets include binary files
        self.objects[key] = data
        bucket = self.buckets[payload["Bucket"]]
        etag = hashlib.md5(data, usedforsecurity=False).hexdigest()
        bucket.setdefault("etags", {})[key] = etag
        # A versioned bucket mints a new id for every put, even of identical bytes.
        self.version_seq += 1
        version = short(key, etag, str(self.version_seq), uuid.uuid4().hex)
        bucket["versions"].append({"Key": key, "VersionId": version})
        self.puts.append({k: v for k, v in payload.items() if k != "Body"})
        return {"ETag": f'"{etag}"', "VersionId": version}

    def s3api_list_objects_v2(self, payload):
        bucket = self.buckets.get(payload["Bucket"])
        if bucket is None:
            raise self.error("s3api", "list-objects-v2", "NoSuchBucket")
        return {"Contents": [{"Key": key, "ETag": f'"{etag}"'}
                             for key, etag in sorted(bucket.get("etags", {}).items())]}

    # ---- CloudFront ---------------------------------------------------------------------------
    def cloudfront_create_invalidation(self, payload):
        batch = payload["InvalidationBatch"]
        known = self.invalidations.setdefault(payload["DistributionId"], {})
        reference = batch["CallerReference"]
        if reference not in known:  # the same reference and batch returns the same invalidation
            known[reference] = {"Id": "I" + short(reference), "polls": 0, "batch": batch}
        return {"Invalidation": {"Id": known[reference]["Id"], "Status": "InProgress"}}

    def cloudfront_get_invalidation(self, payload):
        for entry in self.invalidations.get(payload["DistributionId"], {}).values():
            if entry["Id"] == payload["Id"]:
                entry["polls"] += 1
                done = entry["polls"] > 1  # one polling round in progress, then complete
                return {"Invalidation": {"Id": entry["Id"],
                                         "Status": "Completed" if done else "InProgress"}}
        raise self.error("cloudfront", "get-invalidation", "NoSuchInvalidation")

    def s3api_get_bucket_tagging(self, payload):
        bucket = self.buckets.get(payload["Bucket"])
        if bucket is None:
            raise self.error("s3api", "get-bucket-tagging", "NoSuchBucket")
        if not bucket["tags"]:
            raise self.error("s3api", "get-bucket-tagging", "NoSuchTagSet")
        return {"TagSet": [{"Key": k, "Value": v} for k, v in bucket["tags"].items()]}

    def s3api_list_object_versions(self, payload):
        bucket = self.buckets.get(payload["Bucket"])
        if bucket is None:
            raise self.error("s3api", "list-object-versions", "NoSuchBucket")
        prefix = payload.get("Prefix", "")
        return {"Versions": [v for v in bucket["versions"] if v["Key"].startswith(prefix)],
                "DeleteMarkers": [m for m in bucket["markers"] if m["Key"].startswith(prefix)]}

    def s3api_delete_objects(self, payload):
        bucket = self.buckets[payload["Bucket"]]
        gone = {(o["Key"], o["VersionId"]) for o in payload["Delete"]["Objects"]}
        for field in ("versions", "markers"):
            bucket[field] = [o for o in bucket[field] if (o["Key"], o["VersionId"]) not in gone]
        alive = {o["Key"] for o in bucket["versions"]}
        bucket["etags"] = {k: v for k, v in bucket.get("etags", {}).items() if k in alive}
        return {}

    def s3api_list_multipart_uploads(self, payload):
        return {"Uploads": list(self.buckets[payload["Bucket"]]["uploads"])}

    def s3api_abort_multipart_upload(self, payload):
        bucket = self.buckets[payload["Bucket"]]
        bucket["uploads"] = [u for u in bucket["uploads"] if u["UploadId"] != payload["UploadId"]]
        return {}

    def s3api_delete_bucket(self, payload):
        bucket = self.buckets.get(payload["Bucket"])
        if bucket is None:
            raise self.error("s3api", "delete-bucket", "NoSuchBucket")
        if bucket["versions"] or bucket["markers"] or bucket["uploads"]:
            raise self.error("s3api", "delete-bucket", "BucketNotEmpty")
        del self.buckets[payload["Bucket"]]
        return {}

    # ---- ECR ----------------------------------------------------------------------------------
    def register_image(self, repository, tag):
        repo = self.repos[repository]
        if tag in repo["images"]:  # the repositories are immutable-tag
            raise self.error("ecr", "put-image", "ImageTagAlreadyExistsException")
        digest = "sha256:" + hashlib.sha256(f"{repository}:{tag}".encode()).hexdigest()
        repo["images"][tag] = digest
        return digest

    def repository(self, name, operation):
        if name not in self.repos:
            raise self.error("ecr", operation, "RepositoryNotFoundException")
        return self.repos[name]

    def ecr_get_authorization_token(self, payload):
        token = base64.b64encode(b"AWS:simulated-registry-password").decode()
        return {"authorizationData": [{"authorizationToken": token}]}

    def ecr_describe_images(self, payload):
        repo = self.repository(payload["repositoryName"], "describe-images")
        tag = payload["imageIds"][0]["imageTag"]
        if tag not in repo["images"]:
            raise self.error("ecr", "describe-images", "ImageNotFoundException")
        return {"imageDetails": [{"imageDigest": repo["images"][tag], "imageTags": [tag]}]}

    def ecr_describe_image_scan_findings(self, payload):
        return {"imageScanFindings": {"findingSeverityCounts": {}}}

    def ecr_list_images(self, payload):
        repo = self.repository(payload["repositoryName"], "list-images")
        return {"imageIds": [{"imageDigest": d, "imageTag": t} for t, d in repo["images"].items()]}

    def ecr_batch_delete_image(self, payload):
        repo = self.repository(payload["repositoryName"], "batch-delete-image")
        for image in payload["imageIds"]:
            repo["images"].pop(image.get("imageTag"), None)
        return {}

    def ecr_delete_repository(self, payload):
        repo = self.repository(payload["repositoryName"], "delete-repository")
        if repo["images"] and not payload.get("force"):
            raise self.error("ecr", "delete-repository", "RepositoryNotEmptyException")
        del self.repos[payload["repositoryName"]]
        return {}

    def ecr_list_tags_for_resource(self, payload):
        repo = self.repository(payload["resourceArn"].rsplit("/", 1)[1], "list-tags-for-resource")
        return {"tags": [{"Key": k, "Value": v} for k, v in repo["tags"].items()]}

    # ---- Aurora ------------------------------------------------------------------------------
    def rds_describe_db_clusters(self, payload):
        found = self.clusters.get(payload["DBClusterIdentifier"])
        if found is None:
            raise self.error("rds", "describe-db-clusters", "DBClusterNotFoundFault")
        if found["status"] == "deleting":
            del self.clusters[payload["DBClusterIdentifier"]]
            self.after_cluster_delete(payload["DBClusterIdentifier"])
            return {"DBClusters": [{"Status": "deleting"}]}
        return {"DBClusters": [{"Status": found["status"]}]}

    def after_cluster_delete(self, identifier):
        for snapshot in self.snapshots.values():
            if snapshot["cluster"] == identifier:
                snapshot["status"] = "available"

    def rds_describe_db_instances(self, payload):
        found = self.instances.get(payload["DBInstanceIdentifier"])
        if found is None:
            raise self.error("rds", "describe-db-instances", "DBInstanceNotFoundFault")
        if found["status"] == "deleting":
            del self.instances[payload["DBInstanceIdentifier"]]
        return {"DBInstances": [{"DBInstanceStatus": found["status"]}]}

    def rds_modify_db_cluster(self, payload):
        self.clusters[payload["DBClusterIdentifier"]]["protected"] = payload["DeletionProtection"]
        return {}

    def rds_delete_db_instance(self, payload):
        found = self.instances.get(payload["DBInstanceIdentifier"])
        if found is None:
            raise self.error("rds", "delete-db-instance", "DBInstanceNotFoundFault")
        found["status"] = "deleting"
        return {}

    def rds_delete_db_cluster(self, payload):
        identifier = payload["DBClusterIdentifier"]
        found = self.clusters.get(identifier)
        if found is None:
            raise self.error("rds", "delete-db-cluster", "DBClusterNotFoundFault")
        if self.instances:
            raise self.error("rds", "delete-db-cluster", "InvalidDBClusterStateFault")
        if found["protected"]:
            raise self.error("rds", "delete-db-cluster", "InvalidParameterCombination")
        if not payload["SkipFinalSnapshot"]:
            self.snapshots[payload["FinalDBSnapshotIdentifier"]] = {
                "cluster": identifier, "status": "creating", "tags": {}}
        found["status"] = "deleting"
        return {}

    def rds_describe_db_cluster_snapshots(self, payload):
        found = self.snapshots.get(payload["DBClusterSnapshotIdentifier"])
        if found is None:
            raise self.error("rds", "describe-db-cluster-snapshots", "DBClusterSnapshotNotFound")
        return {"DBClusterSnapshots": [{"Status": found["status"]}]}

    def rds_add_tags_to_resource(self, payload):
        snapshot = payload["ResourceName"].rsplit(":", 1)[1]
        self.snapshots[snapshot]["tags"].update(tags_of(payload["Tags"]))
        return {}

    def rds_list_tags_for_resource(self, payload):
        arn = payload["ResourceName"]
        kind, identifier = arn.split(":")[-2:]
        table = self.clusters if kind == "cluster" else self.instances
        if identifier not in table:
            raise self.error("rds", "list-tags-for-resource",
                             "DBClusterNotFoundFault" if kind == "cluster"
                             else "DBInstanceNotFoundFault")
        return {"TagList": [{"Key": k, "Value": v} for k, v in table[identifier]["tags"].items()]}

    # ---- SSM / Secrets Manager / Logs --------------------------------------------------------
    def ssm_describe_parameters(self, payload):
        name = payload["ParameterFilters"][0]["Values"][0]
        return {"Parameters": [{"Name": name}] if name in self.params else []}

    def ssm_put_parameter(self, payload):
        name = payload["Name"]
        if name in self.params and not payload.get("Overwrite"):
            raise self.error("ssm", "put-parameter", "ParameterAlreadyExists")
        if name not in self.params:
            self.params[name] = tags_of(payload.get("Tags", []))
        self.param_values[name] = payload["Value"]
        return {"Version": 1}

    def ssm_delete_parameter(self, payload):
        if payload["Name"] not in self.params:
            raise self.error("ssm", "delete-parameter", "ParameterNotFound")
        del self.params[payload["Name"]]
        self.param_values.pop(payload["Name"], None)
        return {}

    def ssm_list_tags_for_resource(self, payload):
        tags = self.params.get(payload["ResourceId"], {})
        return {"TagList": [{"Key": k, "Value": v} for k, v in tags.items()]}

    def ssm_get_parameters_by_path(self, payload):
        return {"Parameters": [{"Name": n} for n in sorted(self.params)
                               if n.startswith(payload["Path"])]}

    def secretsmanager_get_secret_value(self, payload):
        return {"SecretString": json.dumps({"username": "dc2bootstrap",
                                            "password": "simulated-master-password"})}

    def logs_describe_log_groups(self, payload):
        region, account = self.s.region, self.s.account
        return {"logGroups": [
            {"logGroupName": n, "arn": f"arn:aws:logs:{region}:{account}:log-group:{n}:*"}
            for n in sorted(self.groups) if n.startswith(payload["logGroupNamePrefix"])]}

    def logs_delete_log_group(self, payload):
        if payload["logGroupName"] not in self.groups:
            raise self.error("logs", "delete-log-group", "ResourceNotFoundException")
        del self.groups[payload["logGroupName"]]
        return {}

    def logs_list_tags_for_resource(self, payload):
        name = payload["resourceArn"].split("log-group:", 1)[1]
        if name not in self.groups:
            raise self.error("logs", "list-tags-for-resource", "ResourceNotFoundException")
        return {"tags": dict(self.groups[name])}

    # ---- ECS ------------------------------------------------------------------------------------
    def ecs_run_task(self, payload):
        arn = f"arn:aws:ecs:{self.s.region}:{self.s.account}:task/sim/{payload['clientToken'][:12]}"
        self.tasks[arn] = {"definition": payload["taskDefinition"], "polls": 0, "stopped": False,
                           "started_by": payload.get("startedBy")}
        staged = self.param_values.get(f"/dc2/{self.s.env}/bootstrap-input")
        if "bootstrap" in payload["taskDefinition"] and staged:
            # What a real bootstrap task does: set the roles' passwords from its input.
            self.role_passwords = json.loads(staged)["role_passwords"]
        return {"tasks": [{"taskArn": arn}], "failures": []}

    def ecs_describe_tasks(self, payload):
        out, missing = [], []
        for arn in payload["tasks"]:
            task = self.tasks.get(arn)
            if task is None:  # ECS forgets stopped tasks after about an hour
                missing.append({"arn": arn, "reason": "MISSING"})
                continue
            task["polls"] += 1
            if task["stopped"] and task.get("lag", 0) > 0:
                task["lag"] -= 1  # asked to stop, still draining: ECS reports RUNNING a while
                stopped = False
            else:
                stopped = task["stopped"] or task["polls"] > 1
            code = next((c for key, c in self.task_exit.items() if key in task["definition"]), 0)
            out.append({"taskArn": arn, "taskDefinitionArn": task["definition"],
                        "startedBy": task.get("started_by"),
                        "lastStatus": "STOPPED" if stopped else "RUNNING",
                        "containers": [{"exitCode": code}] if stopped else []})
        return {"tasks": out, "failures": missing}

    def ecs_list_tasks(self, payload):
        return {"taskArns": [a for a, t in self.tasks.items()
                             if not t["stopped"] and t["polls"] <= 1]}

    def ecs_stop_task(self, payload):
        self.tasks[payload["task"]]["stopped"] = True
        self.tasks[payload["task"]]["lag"] = self.stop_lag
        return {}

    def ecs_describe_task_definition(self, payload):
        return {"taskDefinition": {"taskDefinitionArn": payload["taskDefinition"]}}

    # ---- tagging ------------------------------------------------------------------------
    def resourcegroupstaggingapi_get_resources(self, payload):
        run = payload["TagFilters"][0]["Values"][0]
        region, account = self.s.region, self.s.account
        found = []

        def add(arn, tags):
            if tags.get(RUN_KEY) == run and tags.get(PROJECT_KEY):
                found.append({"ResourceARN": arn})

        for name, bucket in self.buckets.items():
            add(f"arn:aws:s3:::{name}", bucket["tags"])
        for name, repo in self.repos.items():
            add(f"arn:aws:ecr:{region}:{account}:repository/{name}", repo["tags"])
        for name, tags in self.params.items():
            add(f"arn:aws:ssm:{region}:{account}:parameter{name}", tags)
        for name, snap in self.snapshots.items():
            add(f"arn:aws:rds:{region}:{account}:cluster-snapshot:{name}", snap["tags"])
        for name, stack in self.stacks.items():
            if stack["status"] != "DELETE_COMPLETE":
                add(f"arn:aws:cloudformation:{region}:{account}:stack/{name}/{stack['id']}",
                    stack["tags"])
        return {"ResourceTagMappingList": found}

    # ---- seeding from a real run journal ---------------------------------------------------
    def seed(self, meta):
        """Rebuild the simulated account from what a real run recorded, tagged as it would be."""
        tags = {PROJECT_KEY: "dc2-v1", RUN_KEY: meta["run_id"]}
        resources = meta["resources"]
        for stack in resources.get("stacks", []):
            self.stacks[stack] = {"status": "CREATE_COMPLETE", "id": f"id-{short(stack)}",
                                  "tags": dict(tags), "resources": [], "outputs": {},
                                  "changesets": {}, "template": None}
        for name in resources.get("buckets", []):
            self.buckets[name] = {"tags": dict(tags), "versions": [], "markers": [], "uploads": []}
        for name in resources.get("repositories", []):
            self.repos[name] = {"tags": dict(tags), "images": {}}
        for name in resources.get("db_clusters", []):
            self.clusters[name] = {"status": "available", "protected": True, "tags": dict(tags)}
        for name in resources.get("db_instances", []):
            self.instances[name] = {"status": "available", "tags": dict(tags)}
        for name in resources.get("log_groups", []):
            self.groups[name] = dict(tags)


class SimulatedDocker:
    simulated = True

    def __init__(self, aws=None):
        self.aws, self.commands = aws, []
        # How the last answer was produced, for the plan. None for commands with no such
        # distinction (login, tag, push), which are always simulated.
        self.basis = None

    def __call__(self, argv, *, stdin=None):
        self.commands.append(list(argv))
        self.basis = None
        if argv[0] == "login":
            return "Login Succeeded\n"
        if argv[:2] == ["image", "inspect"]:
            self.basis = "simulated: sha256 of the image reference"
            return f"linux/amd64 sha256:{hashlib.sha256(argv[-1].encode()).hexdigest()}\n"
        if argv[0] == "push" and self.aws is not None:
            match = re.fullmatch(r".*/(?P<repo>[^/:]+):(?P<tag>[^/:]+)", argv[1])
            digest = self.aws.register_image(match["repo"], match["tag"])
            return f"{match['tag']}: digest: {digest} size: 1234\n"
        return ""


_INSPECT_ANSWER = re.compile(r"linux/[a-z0-9]+ sha256:[0-9a-f]{64}")


def daemon_inspect(argv):
    """The local Docker daemon's answer to `image inspect`, or None when it cannot give one.

    This is the only process a dry run may start, it is read-only, and the argument shape is
    pinned: exactly `image inspect --format <template> <plain reference>`. Anything else is a
    programming error here, never forwarded to Docker. No DOCKER_CONFIG override: inspect
    needs no registry credentials, and the user's Docker context is what finds the daemon.
    """
    if (
        len(argv) != 5
        or argv[:3] != ["image", "inspect", "--format"]
        or re.search(r"[\s;|&$`]", argv[4])
        or argv[4].startswith("-")
    ):
        raise ValueError("Only `docker image inspect --format <template> <image>` is allowed")
    try:
        done = subprocess.run(
            ["docker", *argv], env=sanitized_environment(), capture_output=True, text=True,
            timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    answer = done.stdout.strip()
    return answer if done.returncode == 0 and _INSPECT_ANSWER.fullmatch(answer) else None


class ObservingDocker(SimulatedDocker):
    """A dry run's Docker: `image inspect` is observed, everything else stays simulated.

    The build evidence's `config_id` is what a real `image inspect` returns for the image it
    verified, so a dry run given real evidence has to see the real daemon's id or the images
    step can never agree with it. Only references that evidence names are looked up; when the
    daemon is unreachable or does not hold the image, the evidence's own id answers instead.
    `login`, `tag` and `push` never leave the simulation.
    """

    def __init__(self, aws=None, known=None, inspect=None):
        super().__init__(aws)
        self.known = dict(known or {})
        self._inspect = inspect

    def __call__(self, argv, *, stdin=None):
        if argv[:2] == ["image", "inspect"] and argv[-1] in self.known:
            self.commands.append(list(argv))
            observed = (self._inspect or daemon_inspect)(argv)
            if observed:
                self.basis = "observed: local Docker daemon"
                return observed + "\n"
            self.basis = "simulated: build evidence config_id (image not observable in the daemon)"
            return f"linux/amd64 {self.known[argv[-1]]}\n"
        return super().__call__(argv, stdin=stdin)


def simulated_http(method, url, headers, body, timeout):
    raise AwsError("http", method, "DryRunNoNetwork", "a dry run performs no network I/O")


__all__ = ["SimulatedAws", "SimulatedDocker", "ObservingDocker", "simulated_http",
           "HANDLERS", "QUEUES"]
