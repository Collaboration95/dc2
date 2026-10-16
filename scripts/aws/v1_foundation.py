"""Create and execute one scoped V1 foundation CREATE change set.

Only the AWS operator runs this entrypoint. No application/session activation.
Cost publication is a prerequisite; pass its local Markdown receipt path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.aws.v1_operator import (
    ACCOUNT,
    NAMESPACE,
    REGION,
    aws,
    private_receipt,
    verify_identity,
)

FORBIDDEN = {
    "AWS::EC2::Instance", "AWS::EC2::NatGateway", "AWS::ElasticLoadBalancingV2::LoadBalancer",
    "AWS::ElasticLoadBalancing::LoadBalancer", "AWS::ElastiCache::CacheCluster",
    "AWS::ElastiCache::ReplicationGroup", "AWS::ECS::Service", "AWS::RDS::DBProxy",
}


def validate_foundation(template: dict[str, Any], parameters: list[dict[str, str]]) -> None:
    """Reject legacy topology and application creation before contacting AWS."""
    supplied = {p["ParameterKey"]: p.get("ParameterValue", "") for p in parameters}
    defaults = {k: str(v.get("Default", "")) for k, v in template.get("Parameters", {}).items()}
    values = defaults | supplied
    if values.get("DeployApplications", "").lower() != "false":
        raise ValueError("foundation requires explicit DeployApplications=false")
    if NAMESPACE not in values.values():
        raise ValueError("foundation parameters must bind the exact project namespace")
    if values.get("SessionOpen", "false").lower() != "false":
        raise ValueError("foundation requires SessionOpen=false")

    def evaluate(value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if "Ref" in value:
            return values[value["Ref"]]
        if "Condition" in value:
            return evaluate(template["Conditions"][value["Condition"]])
        if "Fn::Equals" in value:
            a, b = value["Fn::Equals"]
            return str(evaluate(a)) == str(evaluate(b))
        if "Fn::And" in value:
            return all(evaluate(x) for x in value["Fn::And"])
        raise ValueError("unsupported foundation condition; inspect manually")

    resources = template.get("Resources", {})
    if not resources:
        raise ValueError("empty foundation")
    for name, resource in resources.items():
        kind = resource.get("Type", "")
        props = resource.get("Properties", {})
        if kind in FORBIDDEN or kind.startswith("Custom::"):
            raise ValueError(f"forbidden foundation resource {name}: {kind}")
        if kind == "AWS::EC2::VPCEndpoint" and props.get("VpcEndpointType") != "Gateway":
            raise ValueError("only free gateway endpoints are permitted")
        if kind == "AWS::RDS::DBCluster":
            scaling = props.get("ServerlessV2ScalingConfiguration", {})
            if scaling.get("MinCapacity") != 0 or scaling.get("MaxCapacity") != 2:
                raise ValueError("Aurora must retain 0..2 ACU foundation bounds")
        if kind in {"AWS::Lambda::Function", "AWS::Lambda::EventSourceMapping",
                    "AWS::ECS::TaskDefinition", "AWS::Events::Rule"}:
            condition = resource.get("Condition")
            if not condition or evaluate(template["Conditions"][condition]) is not False:
                raise ValueError(f"application resource {name} must be disabled by condition")


def checked(args: list[str], output: Path, name: str) -> dict[str, Any]:
    result = aws(args)
    private_receipt(output, name, result)
    if result["returncode"]:
        raise RuntimeError(f"AWS {name} failed; inspect private receipt")
    return result["data"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "execute", "observe"])
    parser.add_argument("--template", type=Path)
    parser.add_argument("--parameters", type=Path)
    parser.add_argument("--cost-receipt", type=Path)
    parser.add_argument("--staging-bucket")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    private_receipt(args.output_dir, "identity", verify_identity())
    if args.action == "prepare":
        if not all([args.template, args.parameters, args.cost_receipt]):
            parser.error("prepare requires template, parameters and published cost receipt")
        body = args.template.read_bytes()
        params = json.loads(args.parameters.read_text())
        validate_foundation(json.loads(body), params)
        if not args.cost_receipt.read_text().strip():
            raise ValueError("empty cost receipt")
        digest = hashlib.sha256(body).hexdigest()
        location = ["--template-body", f"file://{args.template.resolve()}"]
        if len(body) > 51200:
            expected_bucket = f"{NAMESPACE}-artifacts-{ACCOUNT}"
            if args.staging_bucket != expected_bucket:
                raise ValueError("oversize template requires the exact project staging bucket")
            key = f"templates/{digest}.json"
            checked(["s3api", "put-object", "--bucket", expected_bucket, "--key", key,
                     "--body", str(args.template.resolve()), "--server-side-encryption", "AES256"],
                    args.output_dir, "foundation-template-upload")
            location = ["--template-url", f"https://{expected_bucket}.s3.{REGION}.amazonaws.com/{key}"]
        checked(["cloudformation", "validate-template", *location],
                args.output_dir, "template-validation")
        created = checked([
            "cloudformation", "create-change-set", "--stack-name", NAMESPACE,
            "--change-set-name", f"foundation-{digest[:12]}", "--change-set-type", "CREATE",
            *location,
            "--parameters", f"file://{args.parameters.resolve()}",
            "--capabilities", "CAPABILITY_NAMED_IAM", "--tags",
            f"Key=Project,Value={NAMESPACE}", "--client-token", f"foundation-{digest}",
        ], args.output_dir, "foundation-change-set")
        private_receipt(args.output_dir, "foundation-inputs", {
            "template_sha256": digest,
            "parameters_sha256": hashlib.sha256(args.parameters.read_bytes()).hexdigest(),
            "cost_receipt_sha256": hashlib.sha256(args.cost_receipt.read_bytes()).hexdigest(),
            "change_set": created["Id"], "stack": created["StackId"],
        })
        print("Foundation CREATE change set requested; resources not executed.")
    else:
        inputs = json.loads((args.output_dir / "aws-foundation-inputs.json").read_text())
        state = checked(["cloudformation", "describe-change-set", "--stack-name", NAMESPACE,
                         "--change-set-name", inputs["change_set"]], args.output_dir,
                        "foundation-change-set-observed")
        if state["StackId"] != inputs["stack"] or state.get("StackName") != NAMESPACE:
            raise ValueError("change-set scope mismatch")
        if args.action == "execute":
            if state.get("Status") != "CREATE_COMPLETE":
                raise ValueError("change set is not CREATE_COMPLETE")
            if state.get("ExecutionStatus") != "AVAILABLE":
                raise ValueError("change set is not AVAILABLE")
            changes = state.get("Changes", [])
            if not changes or any(c.get("ResourceChange", {}).get("Action") != "Add"
                                  for c in changes):
                raise ValueError("initial foundation permits only Add changes")
            verify_identity()
            checked(["cloudformation", "execute-change-set", "--stack-name", NAMESPACE,
                     "--change-set-name", inputs["change_set"], "--client-request-token",
                     f"execute-{inputs['template_sha256']}"], args.output_dir,
                    "foundation-execute")
            print("Foundation execution requested; inspect stack events before further work.")
        else:
            print(f"Change set: {state['Status']} / {state.get('ExecutionStatus')}")
        checked(["cloudformation", "describe-stacks", "--stack-name", NAMESPACE],
                args.output_dir, "foundation-stack-observed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
