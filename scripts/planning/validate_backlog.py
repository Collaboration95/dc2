"""Check the local delivery DAG and its mapped GitHub identities."""

import json
from pathlib import Path

root = Path(__file__).resolve().parents[2] / "docs/execution"
packet = json.loads((root / "backlog.json").read_text())
remote = json.loads((root / "github-map.json").read_text())
issues = {item["key"]: item for item in packet["issues"]}
epics = {item["key"]: item for item in packet["epics"]}
assert len(issues) == len(packet["issues"]), "Duplicate issue keys"
assert len(epics) == len(packet["epics"]), "Duplicate epic keys"
assert set(issues) == set(remote["issues"]), "GitHub issue mapping mismatch"
assert set(epics) == set(remote["epics"]), "GitHub epic mapping mismatch"
for key, item in issues.items():
    assert item["epic"] in epics, f"{key}: unknown epic"
    assert item["acceptance"] and item["verification"], f"{key}: missing acceptance or verification"
    assert item["personas"], f"{key}: no persona value"
    assert set(item["dependencies"]) <= set(issues), f"{key}: unknown dependency"
    assert all(issues[d]["wave"] <= item["wave"] for d in item["dependencies"])
    body = (root / "issues" / f"{key}.md").read_text()
    assert f"agent-orchestration:issue-key=dc2-{key}" in body
    assert remote["issues"][key]["url"].endswith("/" + str(remote["issues"][key]["number"]))
done = set()
while len(done) < len(issues):
    ready = {k for k, i in issues.items() if k not in done and set(i["dependencies"]) <= done}
    assert ready, "Dependency cycle"
    done |= ready
print(f"PASS: {len(epics)} epics, {len(issues)} contracts, GitHub identities and acyclic waves")
