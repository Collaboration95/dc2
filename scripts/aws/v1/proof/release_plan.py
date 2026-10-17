"""Write the #65 release plan (plan.json) and its image bundles for a stack that is deployed.

`evidence release` needs three image sets for one owner: `baseline` (what the stack runs now),
`good` (a newly built image to promote, then roll back from) and optionally `bad` (an image
that must fail the public smoke so the restore path runs for real). Each needs a bundle the
release CLI will accept, a pinned migration task definition holding that exact image (and, for
Processing, a worker definition), and a compatibility attestation. This assembles all of it
from facts it can check:

  * the deploy journal and stack outputs (baseline digests, repositories, definitions);
  * `deploy/v1/build_and_verify.py` evidence for each image set (config ids, source commit,
    runtime contents; it must be LOCAL_ARTIFACT_PASS with no failures);
  * the registry, asked by tag (digest, and a COMPLETE scan with no HIGH/CRITICAL finding).

What it cannot check it states: the unit tests behind each image (`--tests-passed` is an
operator attestation, as in the bundle gate), and that good/bad add no migration beyond
`--target-revision` (`--attest-schema-unchanged`). The one mutation is registering a new task
definition revision per good/bad image, copied from the deployed one with only the image
swapped; `--deregister` retires them after the proof.
"""

import hashlib
import json
import re
from pathlib import Path

from scripts.aws.transport import OperationError
from scripts.aws.v1 import deploy
from scripts.aws.v1.proof import release
from scripts.aws.v1.proof.core import ProofError, private_write
from scripts.aws.v1.release import validate_inputs

DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
SOURCE = re.compile(r"[0-9a-f]{40}")
# owner -> ((kind, build-evidence image, repository output), ...)
IMAGES = {
    "media": (("api", "media", "MediaRepositoryUri"),),
    "processing": (("api", "processing", "ProcessingRepositoryUri"),
                   ("worker", "worker", "WorkerRepositoryUri")),
}
RUNTIME = {"api": "lambda-api", "worker": "finite-worker"}
MIGRATION_OUTPUT = {"media": "MediaMigrationTaskDefinitionArn",
                    "processing": "ProcessingMigrationTaskDefinitionArn"}
# The register-task-definition fields the operator contract admits; describe returns more.
COPIED = ("family", "containerDefinitions", "cpu", "memory", "networkMode",
          "requiresCompatibilities", "executionRoleArn", "runtimePlatform", "taskRoleArn")


def load_evidence(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        raise ProofError("A build evidence file is unreadable JSON") from None
    if (not isinstance(data, dict) or data.get("status") != "LOCAL_ARTIFACT_PASS"
            or data.get("failures") or not isinstance(data.get("images"), dict)):
        raise ProofError("Build evidence must be LOCAL_ARTIFACT_PASS with no failed check "
                         "(deploy/v1/build_and_verify.py --out)")
    return data


def evidence_image(evidence, name):
    image = evidence["images"].get(name)
    if (not isinstance(image, dict) or image.get("build_exit_code") != 0
            or not DIGEST.fullmatch(str(image.get("config_id")))
            or not SOURCE.fullmatch(str(image.get("source_sha")))
            or not isinstance(image.get("runtime_contents"), dict)):
        raise ProofError(f"The build evidence has no verified {name} image")
    return image


def local_head(owner):
    """The owner's Alembic head in this checkout (the revision a release migrates to)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(deploy.ROOT / owner / "alembic.ini"))
    cfg.set_main_option("script_location", str(deploy.ROOT / owner / "migrations"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    if len(heads) != 1:
        raise ProofError(f"{owner} migrations must have exactly one head")
    return heads[0]


class Planner:
    def __init__(self, ctx, owner):
        self.ctx, self.owner = ctx, owner
        journal = deploy.DeployJournal(
            ctx.state_dir / "deploy-journal.json", station=ctx.data["operator_station"],
            environment=ctx.data["environment_id"])
        if not journal.exists():
            raise ProofError("No deploy journal in the state directory; this stack was not "
                             "deployed from here")
        self.deployed = journal.view()
        self.registered = []  # revisions this run created, for the plan and for cleanup

    def repository(self, output):
        uri = {**self.ctx.outputs, **self.deployed.get("outputs", {})}.get(output)
        if not uri or "/" not in uri:
            raise ProofError(f"The deploy journal has no {output}")
        return uri

    def aws(self, service, operation, payload):
        try:
            return self.ctx.aws.call(service, operation, payload, deadline=self.ctx.deadline(120))
        except OperationError as error:
            raise ProofError(str(error)) from None
        except Exception as error:  # a transport surprise: the class, never its message
            raise ProofError(f"{service} {operation} failed ({type(error).__name__})") from None

    def digest_of(self, repository, tag):
        reply = self.aws("ecr", "describe-images", {
            "repositoryName": repository.split("/", 1)[1], "imageIds": [{"imageTag": tag}]})
        found = reply.get("imageDetails") or []
        if len(found) != 1 or not DIGEST.fullmatch(str(found[0].get("imageDigest"))):
            raise ProofError(f"{tag} is not in the repository; push it first")
        return found[0]["imageDigest"]

    def scan(self, repository, digest, tag):
        """(report hash, fixable HIGH/CRITICAL). A pending or blocking scan is a refusal."""
        reply = self.aws("ecr", "describe-image-scan-findings", {
            "repositoryName": repository.split("/", 1)[1], "imageId": {"imageDigest": digest}})
        if reply.get("imageScanStatus", {}).get("status") != "COMPLETE":
            raise ProofError(f"The scan of {tag} is not COMPLETE yet")
        counts = reply.get("imageScanFindings", {}).get("findingSeverityCounts", {})
        blocking = counts.get("HIGH", 0) + counts.get("CRITICAL", 0)
        if blocking:
            raise ProofError(f"{tag} has {blocking} HIGH/CRITICAL scan findings; the release "
                             "gate blocks it")
        canonical = json.dumps(reply, sort_keys=True, default=str)
        return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest(), blocking

    def image_set(self, role, tags, evidence, tests_passed):
        """{bundle, image_uri, digests}: one registry-verified image set and its bundle."""
        bundle, digests = {}, {}
        for kind, name, output in IMAGES[self.owner]:
            image = evidence_image(evidence, name)
            repository = self.repository(output)
            digest = self.digest_of(repository, tags[name])
            report, blocking = self.scan(repository, digest, tags[name])
            gate = {"status": "PASS", "config_id": image["config_id"],
                    "source_sha": image["source_sha"]}
            bundle[kind] = {
                "owner": self.owner, "platform": "linux/amd64",
                "source_sha": image["source_sha"], "config_id": image["config_id"],
                # `docker push` of a local image keeps its config digest as the image id.
                "manifest_config_id": image["config_id"], "manifest_digest": digest,
                "tests": {**gate, "passed": tests_passed},
                "artifact_test": {**gate, "kind": "local-exact-image-checks"},
                "scan": {**gate, "fixable_high_critical": blocking, "report_sha256": report},
                "runtime_kind": RUNTIME[kind],
                "runtime_contents": image["runtime_contents"],
            }
            digests[kind] = (repository, digest)
        repository, digest = digests["api"]
        return {"role": role, "bundle": bundle, "image_uri": f"{repository}@{digest}",
                "digests": {k: v[1] for k, v in digests.items()}, "repositories": {
                    k: v[0] for k, v in digests.items()}}

    def definition(self, arn):
        reply = self.aws("ecs", "describe-task-definition", {"taskDefinition": arn})
        return reply["taskDefinition"]

    def deployed_definitions(self, baseline):
        """The stack's own definitions, only if they still hold the baseline image."""
        found = {"migration_definition": self.ctx.outputs.get(MIGRATION_OUTPUT[self.owner])}
        if self.owner == "processing":
            found["worker_definition"] = self.ctx.outputs.get("WorkerTaskDefinitionArn")
        for field, arn in found.items():
            kind = "worker" if field == "worker_definition" else "api"
            if not arn:
                raise ProofError(f"The stack outputs have no {field.split('_')[0]} definition")
            held = {c["image"].rsplit("@", 1)[-1]
                    for c in self.definition(arn)["containerDefinitions"]}
            if held != {baseline["digests"][kind]}:
                raise ProofError(
                    f"The stack's {field} no longer holds the baseline image, so it has been "
                    "updated since the deploy; name the image it holds as the baseline")
        return found

    def register_copy(self, arn, image_uri):
        """A new revision of a deployed definition with only the container image replaced."""
        source = self.definition(arn)
        if len(source["containerDefinitions"]) != 1:
            raise ProofError("Only a single-container definition can be copied")
        payload = {k: source[k] for k in COPIED if source.get(k) is not None}
        payload["containerDefinitions"] = [{**source["containerDefinitions"][0],
                                            "image": image_uri}]
        made = self.aws("ecs", "register-task-definition", payload)
        new = made["taskDefinition"]["taskDefinitionArn"]
        self.registered.append(new)
        return new

    def registered_definitions(self, image, base):
        """Definitions for a new image set: the deployed ones with only the image swapped."""
        uris = {kind: f"{image['repositories'][kind]}@{digest}"
                for kind, digest in image["digests"].items()}
        result = {"migration_definition": self.register_copy(
            base["migration_definition"], uris["api"])}
        if self.owner == "processing":
            result["worker_definition"] = self.register_copy(
                base["worker_definition"], uris["worker"])
        return result

    def retire(self):
        """Best effort: a failed run must not leave definition revisions nobody lists."""
        for arn in self.registered:
            try:
                self.ctx.aws.call("ecs", "deregister-task-definition", {"taskDefinition": arn},
                                  deadline=self.ctx.deadline(60))
            except Exception:  # the caller is already failing with its own error
                pass


def write_image(out, role, image, definitions, owner, target):
    bundle_path = out / f"bundle-{role}.json"
    compat_path = out / f"compat-{role}.json"
    private_write(bundle_path, json.dumps(image["bundle"], indent=2, sort_keys=True) + "\n")
    private_write(compat_path, json.dumps({
        "owner": owner, "source_sha": image["bundle"]["api"]["source_sha"],
        "target_revision": target, "additive_only": True, "current_image_compatible": True,
        "prior_image_compatible": True}, indent=2, sort_keys=True) + "\n")
    return {"bundle": str(bundle_path), "image_uri": image["image_uri"],
            "compat_evidence": str(compat_path), **definitions}


def run(ctx, *, owner, baseline_evidence, good, bad=None, tests_passed, target_revision=None,
        attest_schema_unchanged=False, out):
    """Write `out/plan.json`. `good`/`bad` are {"run_id", "evidence"}; the tags are
    `<run_id>-media|processing|worker`, the convention `deploy` pushes with."""
    if not attest_schema_unchanged:
        raise ProofError("--attest-schema-unchanged is required: good, baseline and bad must "
                         "all be compatible with --target-revision (the stack's current head)")
    if type(tests_passed) is not int or tests_passed < 1:
        raise ProofError("--tests-passed must be the number of source tests that passed")
    target = target_revision or local_head(owner)
    planner = Planner(ctx, owner)
    try:
        return assemble(ctx, planner, owner, baseline_evidence, good, bad, tests_passed, target,
                        Path(out))
    except BaseException:
        planner.retire()
        raise


def assemble(ctx, planner, owner, baseline_evidence, good, bad, tests_passed, target, out):
    deployed = planner.deployed["images"]
    tags = {name: deployed[name]["tag"] for _, name, _ in IMAGES[owner]}
    base_evidence = load_evidence(baseline_evidence)
    for _, name, _ in IMAGES[owner]:
        if deployed[name].get("local_id") != evidence_image(base_evidence, name)["config_id"]:
            raise ProofError(f"--baseline-evidence is not the build of the deployed {name} image")
    baseline = planner.image_set("baseline", tags, base_evidence, tests_passed)
    for kind, name, _ in IMAGES[owner]:
        if baseline["digests"][kind] != deployed[name]["digest"]:
            raise ProofError(f"The registry's {tags[name]} is not the digest deploy recorded")
    base = planner.deployed_definitions(baseline)
    sets = {"baseline": (baseline, base)}
    for role, spec in (("good", good), ("bad", bad)):
        if not spec:
            continue
        evidence = load_evidence(spec["evidence"])
        new_tags = {name: f"{spec['run_id']}-{name}" for _, name, _ in IMAGES[owner]}
        image = planner.image_set(role, new_tags, evidence, tests_passed)
        if any(image["digests"][k] == baseline["digests"][k] for k in image["digests"]):
            raise ProofError(f"The {role} image set shares an image with the baseline, so "
                             "promoting it would move nothing; build a different image")
        sets[role] = (image, planner.registered_definitions(image, base))
    plan = {"owner": owner, "target_revision": target,
            "registered_definitions": planner.registered}
    for role, (image, definitions) in sets.items():
        plan[role] = write_image(out, role, image, definitions, owner, target)
    plan_path = out / "plan.json"
    private_write(plan_path, json.dumps(plan, indent=2, sort_keys=True) + "\n")
    # The same offline gates `release promote` applies, so a bad plan fails here, not mid-release.
    release.load_plan(plan_path)
    for role, (image, _) in sets.items():
        item = plan[role]
        validate_inputs(ctx.config, owner=owner, bundle=image["bundle"],
                        image_uri=item["image_uri"],
                        worker_definition=item.get("worker_definition"))
    return {"plan": str(plan_path), "owner": owner, "target_revision": target,
            "images": {role: image["digests"] for role, (image, _) in sets.items()},
            "registered_definitions": len(planner.registered)}


def deregister(ctx, plan_path):
    """Retire the definition revisions `run` registered (an unlisted one is never touched)."""
    plan = release.load_plan(plan_path)
    retired = []
    for arn in plan.get("registered_definitions", []):
        ctx.aws.call("ecs", "deregister-task-definition", {"taskDefinition": arn},
                     deadline=ctx.deadline(60))
        retired.append(arn.rsplit("/", 1)[-1])
    return {"deregistered": retired}
