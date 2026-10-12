"""Set evidence-based issue/project state using the checked-in GitHub map."""

import argparse
import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument("keys", nargs="+")
p.add_argument(
    "--state",
    required=True,
    choices=["Backlog", "Ready", "In progress", "Review", "Blocked", "Done"],
)
p.add_argument("--evidence", default="")
a = p.parse_args()
m = json.loads((root / "docs/execution/github-map.json").read_text())
ledger_path = root / "docs/execution/progress.json"
ledger = json.loads(ledger_path.read_text())
for key in a.keys:
    row = (m["epics"] if key.startswith("E") else m["issues"])[key]
    for field, value in [
        ("Workflow", a.state),
        (
            "Status",
            "Done"
            if a.state == "Done"
            else "In Progress"
            if a.state in ["In progress", "Review"]
            else "Todo",
        ),
    ]:
        f = m["fields"][field]
        opt = next(x for x in f["options"] if x["name"] == value)
        subprocess.run(
            [
                "gh",
                "project",
                "item-edit",
                "--id",
                row["item_id"],
                "--project-id",
                m["project"]["id"],
                "--field-id",
                f["id"],
                "--single-select-option-id",
                opt["id"],
            ],
            check=True,
        )
    if key in ledger["issues"]:
        ledger["issues"][key]["state"] = a.state
        if a.evidence and a.evidence not in ledger["issues"][key]["evidence"]:
            ledger["issues"][key]["evidence"].append(a.evidence)
ledger_path.write_text(json.dumps(ledger, indent=2) + "\n")
print("Updated", ",".join(a.keys), "to", a.state)
