"""Image-pin and task-definition gates in promote, using fake describe-task-definition data."""

import pytest
from test_v1_release import MIGRATION, NEW, WORKER, setup  # noqa: F401

from scripts.aws.transport import OperationError
from scripts.aws.v1.release import promote

MUTATIONS = {"run-task", "update-alias", "update-function-code", "publish-version"}


def mutating(aws):
    return [op for _, op, _ in aws.calls if op in MUTATIONS]


def inspect_with(aws, images):
    """Serve fake task-definition inspect data with the chosen container images."""
    real = aws.call

    def call(service, op, payload, *, deadline):
        result = real(service, op, payload, deadline=deadline)
        if op == "describe-task-definition" and payload["taskDefinition"] in images:
            result["taskDefinition"]["containerDefinitions"] = [
                {"image": image} for image in images[payload["taskDefinition"]]
            ]
        return result

    aws.call = call


def test_image_uri_pin_must_equal_the_tested_bundle_manifest_pin(setup):  # noqa: F811
    config, aws, journal, args = setup
    options = args()
    options["image_uri"] = "repo@sha256:" + "f" * 64
    with pytest.raises(OperationError, match="pin tested registry manifest"):
        promote(config, aws, journal, **options)
    assert not aws.calls  # rejected offline, before any AWS read or write


@pytest.mark.parametrize("uri", ["repo:latest", "repo", NEW.split("@")[1]])
def test_mutable_or_unpinned_image_references_are_rejected(setup, uri):  # noqa: F811
    config, aws, journal, args = setup
    options = args()
    options["image_uri"] = uri
    with pytest.raises(OperationError, match="pin tested registry manifest"):
        promote(config, aws, journal, **options)
    assert not aws.calls


@pytest.mark.parametrize(
    "images",
    [
        ["repo@sha256:" + "f" * 64],  # a different artifact
        [NEW, "repo@sha256:" + "f" * 64],  # one stray sidecar container
        ["repo:latest"],  # mutable tag in the registered definition
    ],
)
def test_migration_definition_must_run_exactly_the_candidate_pin(setup, images):  # noqa: F811
    config, aws, journal, args = setup
    inspect_with(aws, {MIGRATION: images})
    with pytest.raises(OperationError, match="exact owning artifact"):
        promote(config, aws, journal, **args())
    assert mutating(aws) == []


def test_worker_definition_must_run_the_worker_artifact_not_the_api_image(setup):  # noqa: F811
    config, aws, journal, args = setup
    inspect_with(aws, {WORKER: [NEW]})
    with pytest.raises(OperationError, match="exact owning artifact"):
        promote(config, aws, journal, **args("processing"))
    assert mutating(aws) == []


def test_matching_pins_across_api_migration_and_worker_are_accepted(setup):  # noqa: F811
    config, aws, journal, args = setup
    inspect_with(aws, {MIGRATION: [NEW], WORKER: ["repo@sha256:" + "9" * 64]})
    assert promote(config, aws, journal, **args("processing"))["status"] == "promoted"


def test_unpinned_task_definition_revision_is_rejected_before_inspection(setup):  # noqa: F811
    config, aws, journal, args = setup
    options = args()
    options["migration_definition"] = "arn:aws:ecs:ap-southeast-1:123456789012:task-definition/m"
    with pytest.raises(OperationError, match="Pinned task definition revision"):
        promote(config, aws, journal, **options)
    assert mutating(aws) == []


def test_worker_definition_is_refused_for_a_media_release(setup):  # noqa: F811
    config, aws, journal, args = setup
    options = args("media")
    options["worker_definition"] = WORKER
    with pytest.raises(OperationError, match="Media cannot change Processing worker"):
        promote(config, aws, journal, **options)
    assert not aws.calls
