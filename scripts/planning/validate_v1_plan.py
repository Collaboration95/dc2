"""Validate the staged V1/V2 handoff and captured native GitHub relationships."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "docs/execution/aws/v1"


def relation_nodes(value):
    return value.get("nodes", []) if isinstance(value, dict) else value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", type=Path, help="Fresh gh issue-list JSON capture")
    parser.add_argument("--project", type=Path, help="Fresh gh project item-list JSON capture")
    parser.add_argument(
        "--decision-merged",
        action="store_true",
        help="After separately verifying Main merge, require #46 closed/COMPLETED and Done",
    )
    args = parser.parse_args()
    assert not args.decision_merged or (args.remote and args.project), (
        "Decision finalization requires both fresh issue and Project captures"
    )
    packet = json.loads((DIRECTORY / "backlog.json").read_text())
    mapping = json.loads((DIRECTORY / "github-map.json").read_text())
    issues = {item["key"]: item for item in packet["issues"]}
    epics = {item["key"]: item for item in packet["epics"]}
    assert len(issues) == len(packet["issues"]), "Duplicate issue key"
    assert len(epics) == len(packet["epics"]), "Duplicate epic key"
    nodes = {**epics, **issues}
    assert len(nodes) == len(epics) + len(issues), "Epic/issue key collision"
    identities = {**mapping["epics"], **mapping["issues"]}
    assert set(issues) == set(mapping["issues"]), "Incomplete issue map"
    assert set(epics) == set(mapping["epics"]), "Incomplete epic map"
    numbers = [item["number"] for item in identities.values()]
    assert len(numbers) == len(set(numbers)), "Duplicate GitHub identity"
    assert packet["live_actions_authorized"] is False
    assert packet["main_merge_authorized"] is True
    for key, item in nodes.items():
        assert set(item["dependencies"]) <= set(nodes), f"{key}: unknown dependency"
        assert key not in item["dependencies"], f"{key}: self dependency"
        if item["phase"] == "V1":
            assert all(nodes[d]["phase"] == "V1" for d in item["dependencies"]), key
        if key in issues:
            assert item["parent"] in epics, f"{key}: missing parent"
            assert item["phase"] == epics[item["parent"]]["phase"], key
            assert item["acceptance"], f"{key}: missing acceptance"
            if item["kind"] == "implementation":
                assert item["files"], f"{key}: no implementation surface"
            if item["workflow"] == "Ready":
                assert item["phase"] == "V1" and not item["dependencies"], key
        if item["phase"] == "V2":
            assert item["workflow"] == "Backlog", key
            assert "aws2-acceptance" in item["dependencies"], key
        identity = identities[key]
        assert identity["workflow"] == item["workflow"], f"{key}: snapshot workflow drift"
        declared_number = item.get("existing_number", item.get("number"))
        assert declared_number is None or declared_number == identity["number"], key
        assert identity["url"] == (
            "https://github.com/Collaboration95/dc2/issues/" + str(identity["number"])
        ), key
    completed = set()
    while len(completed) < len(nodes):
        ready = {
            key
            for key, item in nodes.items()
            if key not in completed and set(item["dependencies"]) <= completed
        }
        assert ready, "Dependency cycle"
        completed |= ready
    bundle_keys = [key for bundle in packet["implementation_bundles"] for key in bundle["keys"]]
    assert len(bundle_keys) == len(set(bundle_keys)), "Duplicate bundle assignment"
    assert set(bundle_keys) == {k for k, i in issues.items() if i["kind"] == "implementation"}
    assert all(len(bundle["keys"]) >= 4 for bundle in packet["implementation_bundles"])
    ready_keys = {k for k, i in issues.items() if i["workflow"] == "Ready"}
    assert ready_keys == {packet["next_issue_key"]}, "Ambiguous next local handoff"
    for source in json.loads((DIRECTORY / "price-sources.json").read_text())["sources"]:
        assert (
            hashlib.sha256((DIRECTORY / source["file"]).read_bytes()).hexdigest()
            == (source["sha256"])
        ), f"Price provenance drift: {source['file']}"
    remote = None
    if args.remote:
        remote = {item["number"]: item for item in json.loads(args.remote.read_text())}
        for key, identity in identities.items():
            actual = remote[identity["number"]]
            assert actual["title"] == nodes[key]["title"], f"{key}: remote title drift"
            digest = hashlib.sha256(actual["body"].encode()).hexdigest()
            finalizing = key == "aws2-origin-transport" and args.decision_merged
            expected_digest = (
                identity["post_main_merge"]["body_sha256"]
                if finalizing
                else identity["body_sha256"]
            )
            assert digest == expected_digest, f"{key}: remote body drift"
            labels = {label["name"] for label in actual["labels"]}
            assert nodes[key]["phase"].lower() in labels, f"{key}: phase label missing"
            assert ({"v1", "v2"} & labels) == {nodes[key]["phase"].lower()}, key
            blockers = {i["number"] for i in relation_nodes(actual["blockedBy"])}
            assert blockers == {identities[k]["number"] for k in nodes[key]["dependencies"]}, key
            if key in issues:
                assert actual["parent"]["number"] == identities[issues[key]["parent"]]["number"], (
                    key
                )
            if finalizing:
                assert actual["state"] == "CLOSED" and actual["stateReason"] == "COMPLETED", key
            else:
                assert actual["state"] == "OPEN", f"{key}: implementation/evidence closed early"
            if key in epics:
                children = {i["number"] for i in relation_nodes(actual["subIssues"])}
                expected_children = {
                    identities[k]["number"] for k, issue in issues.items() if issue["parent"] == key
                } | set(identity["historical_subissue_numbers"])
                assert children == expected_children, f"{key}: native subissue drift"
        for number in packet["legacy_completed_issue_numbers"]:
            assert remote[number]["state"] == "CLOSED", f"#{number}: legacy state changed"
            assert remote[number]["stateReason"] == "COMPLETED", number
    if args.project:
        project = json.loads(args.project.read_text())
        items = {
            item["content"]["number"]: item
            for item in project["items"]
            if item.get("content", {}).get("type") == "Issue"
        }
        for key, identity in identities.items():
            finalizing = key == "aws2-origin-transport" and args.decision_merged
            expected_workflow = "Done" if finalizing else nodes[key]["workflow"]
            assert items[identity["number"]]["workflow"] == expected_workflow, key
            assert items[identity["number"]]["status"] == ("Done" if finalizing else "Todo"), (
                f"{key}: built-in Status drift"
            )
        for number in packet["legacy_completed_issue_numbers"]:
            assert items[number]["workflow"] == "Done", number
    print(
        f"PASS: {len(epics)} epics, {len(issues)} current handoffs, acyclic dependencies, "
        f"{len(bundle_keys)} implementation issues in four-issue bundles; "
        f"next #{identities[packet['next_issue_key']]['number']}"
    )


if __name__ == "__main__":
    main()
