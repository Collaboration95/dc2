"""Local rejection checks for the live foundation mutation boundary."""

import copy

import pytest

from scripts.aws.v1_foundation import validate_foundation
from scripts.aws.v1_operator import NAMESPACE


def fixture():
    return {
        "Parameters": {"DeployApplications": {"Default": "false"}},
        "Resources": {
            "Database": {
                "Type": "AWS::RDS::DBCluster",
                "Properties": {
                    "ServerlessV2ScalingConfiguration": {"MinCapacity": 0, "MaxCapacity": 2}
                },
            }
        },
    }, [{"ParameterKey": "Namespace", "ParameterValue": NAMESPACE}]


def test_accepts_closed_bounded_foundation():
    template, parameters = fixture()
    validate_foundation(template, parameters)


@pytest.mark.parametrize(
    "kind",
    [
        "AWS::EC2::Instance",
        "AWS::EC2::NatGateway",
        "AWS::ECS::Service",
        "Custom::Unreviewed",
        "AWS::ElastiCache::ReplicationGroup",
    ],
)
def test_rejects_legacy_and_recurring_topology(kind):
    template, parameters = fixture()
    template["Resources"]["Unexpected"] = {"Type": kind}
    with pytest.raises(ValueError, match="forbidden"):
        validate_foundation(template, parameters)


def test_rejects_another_namespace_and_application_activation():
    template, parameters = fixture()
    wrong = copy.deepcopy(parameters)
    wrong[0]["ParameterValue"] = "another-project"
    with pytest.raises(ValueError, match="namespace"):
        validate_foundation(template, wrong)
    parameters.append({"ParameterKey": "DeployApplications", "ParameterValue": "true"})
    with pytest.raises(ValueError, match="DeployApplications=false"):
        validate_foundation(template, parameters)


def test_rejects_paid_endpoint_and_unbounded_db():
    template, parameters = fixture()
    template["Resources"]["Endpoint"] = {
        "Type": "AWS::EC2::VPCEndpoint",
        "Properties": {"VpcEndpointType": "Interface"},
    }
    with pytest.raises(ValueError, match="gateway"):
        validate_foundation(template, parameters)
    del template["Resources"]["Endpoint"]
    template["Resources"]["Database"]["Properties"]["ServerlessV2ScalingConfiguration"][
        "MaxCapacity"
    ] = 16
    with pytest.raises(ValueError, match="ACU"):
        validate_foundation(template, parameters)


def test_application_gate_must_actually_evaluate_false():
    template, parameters = fixture()
    template["Conditions"] = {"WrongGate": {"Fn::Equals": ["true", "true"]}}
    template["Resources"]["Api"] = {"Type": "AWS::Lambda::Function", "Condition": "WrongGate"}
    with pytest.raises(ValueError, match="disabled by condition"):
        validate_foundation(template, parameters)
    template["Conditions"]["WrongGate"] = {"Fn::Equals": [{"Ref": "DeployApplications"}, "true"]}
    validate_foundation(template, parameters)
