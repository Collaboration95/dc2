"""Idempotently publish the reviewed local backlog using authenticated gh only."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / "docs/execution/backlog.json"
MAP = ROOT / "docs/execution/github-map.json"
OWNER = "Collaboration95"
REPO = OWNER + "/dc2"


def gh(*args, decode=False):
    result = subprocess.check_output(["gh", *map(str, args)], cwd=ROOT, text=True)
    return json.loads(result) if decode else result.strip()


def save():
    MAP.write_text(json.dumps(state, indent=2) + "\n")


packet = json.loads(PACKET.read_text())
state = json.loads(MAP.read_text()) if MAP.exists() else {"epics": {}, "issues": {}}
projects = gh(
    "project", "list", "--owner", OWNER, "--limit", "100", "--format", "json", decode=True
)["projects"]
project = next((p for p in projects if p["title"] == packet["project_title"]), None)
if project is None:
    project = gh(
        "project",
        "create",
        "--owner",
        OWNER,
        "--title",
        packet["project_title"],
        "--format",
        "json",
        decode=True,
    )
state["project"] = {k: project[k] for k in ("id", "number", "title", "url")}
save()
number = project["number"]
gh("project", "link", number, "--owner", OWNER, "--repo", REPO)
readme = """Source: docs/execution/plan.md and backlog.json in Collaboration95/dc2.
Six epics, eighteen issues, dependency-ordered waves, grouped multi-issue PRs.
Target three agentic days, maximum five; no AWS or inherited Alibaba actions.
Workflow is the authoritative state: Backlog, Ready, In progress, Review, Blocked, Done.
Built-in Status is a coarse projection (Todo/In Progress/Done).
Wave0 planning must pass independent Sol xhigh review before Wave1 implementation.
After foundation, Processing, Media and client lanes may run in isolated worktrees.
Only mark Done after merge and issue-specific acceptance evidence.
Views via filters: label:epic; wave:"Wave 1"; workflow:Ready; workflow:Review; workflow:Blocked.
The gh CLI cannot save custom views; the default table and these filter recipes remain usable.
One non-repeating 3–5-day delivery timebox uses Wave rather than recurring sprint iterations.
See docs/execution/handoff.md for final evidence, commands and remaining AWS prerequisites.
"""
gh(
    "project",
    "edit",
    number,
    "--owner",
    OWNER,
    "--description",
    "Reviewed pre-AWS local media-platform delivery, grouped PRs and measured evidence.",
    "--readme",
    readme,
)
labels = {
    "epic": ("5319e7", "Parent delivery outcome"),
    "pre-aws": ("0e8a16", "Authorized local delivery; no AWS actions"),
    "planning": ("bfdadc", "Planning and independent review"),
    "foundation": ("1d76db", "Reproducible local setup and checks"),
    "processing": ("fbca04", "Processing service and workers"),
    "media": ("d93f0b", "Media Management and data ownership"),
    "clients": ("0052cc", "Browser and independent Publisher CLI"),
    "verification": ("006b75", "Integrated evidence and release acceptance"),
}
existing_labels = {
    x["name"]
    for x in gh("label", "list", "--repo", REPO, "--limit", "100", "--json", "name", decode=True)
}
for name, (color, description) in labels.items():
    if name not in existing_labels:
        gh("label", "create", name, "--repo", REPO, "--color", color, "--description", description)
fields = gh("project", "field-list", number, "--owner", OWNER, "--format", "json", decode=True)[
    "fields"
]
field_specs = {
    "Workflow": ("SINGLE_SELECT", "Backlog,Ready,In progress,Review,Blocked,Done"),
    "Wave": ("SINGLE_SELECT", ",".join(f"Wave {n}" for n in range(5))),
    "Priority": ("SINGLE_SELECT", "P0,P1,P2"),
    "Risk": ("SINGLE_SELECT", "Low,Medium,High"),
    "Area": ("TEXT", None),
    "Persona": ("TEXT", None),
    "Sequence": ("NUMBER", None),
}
for name, (kind, options) in field_specs.items():
    if not any(f["name"] == name for f in fields):
        args = [
            "project",
            "field-create",
            number,
            "--owner",
            OWNER,
            "--name",
            name,
            "--data-type",
            kind,
            "--format",
            "json",
        ]
        if options:
            args += ["--single-select-options", options]
        gh(*args)
fields = gh("project", "field-list", number, "--owner", OWNER, "--format", "json", decode=True)[
    "fields"
]
state["fields"] = {f["name"]: f for f in fields}
save()
existing = gh(
    "issue",
    "list",
    "--repo",
    REPO,
    "--state",
    "all",
    "--limit",
    "200",
    "--json",
    "number,title,url,body",
    decode=True,
)


def ensure_issue(key, title, body, area, parent=None, deps=(), epic=False):
    marker = f"agent-orchestration:issue-key=dc2-{key}"
    match = next((x for x in existing if marker in x["body"]), None)
    body_path = ROOT / "docs/execution/issues" / f"{key}.md"
    body_path.write_text(body)
    if match:
        gh(
            "issue",
            "edit",
            match["number"],
            "--repo",
            REPO,
            "--title",
            title,
            "--body-file",
            body_path,
        )
        url = match["url"]
        num = match["number"]
    else:
        args = [
            "issue",
            "create",
            "--repo",
            REPO,
            "--title",
            title,
            "--body-file",
            body_path,
            "--label",
            "pre-aws",
            "--label",
            area,
        ]
        if epic:
            args += ["--label", "epic"]
        if parent:
            args += ["--parent", parent]
        if deps:
            args += ["--blocked-by", ",".join(map(str, deps))]
        url = gh(*args)
        num = int(url.rsplit("/", 1)[1])
        existing.append({"number": num, "url": url, "body": body})
    if match and parent:
        gh("issue", "edit", num, "--repo", REPO, "--parent", parent)
    if match and deps:
        gh("issue", "edit", num, "--repo", REPO, "--add-blocked-by", ",".join(map(str, deps)))
    return {"number": num, "url": url}


for e in packet["epics"]:
    children = [i for i in packet["issues"] if i["epic"] == e["key"]]
    body = (
        f"<!-- agent-orchestration:issue-key=dc2-{e['key']} -->\n\n"
        f"Outcome: {e['title']}.\n\nPersonas: {e['personas']}.\n\nChildren: "
        + ", ".join(i["key"] for i in children)
        + ".\n\nCompletion requires all children merged with acceptance evidence "
        "and independent review. No AWS actions. Source: `docs/execution/plan.md`.\n"
    )
    state["epics"][e["key"]] = {
        **state["epics"].get(e["key"], {}),
        **ensure_issue(e["key"], f"[{e['key']}] {e['title']}", body, e["area"], epic=True),
    }
    save()
    print("Epic", e["key"], state["epics"][e["key"]]["url"], flush=True)
for i in packet["issues"]:
    body = (ROOT / "docs/execution/issues" / f"{i['key']}.md").read_text()
    parent = state["epics"][i["epic"]]["number"]
    deps = [state["issues"][k]["number"] for k in i["dependencies"]]
    area = next(e["area"] for e in packet["epics"] if e["key"] == i["epic"])
    body += (
        "\nGitHub parent: #"
        + str(parent)
        + ". Dependencies: "
        + (", ".join("#" + str(n) for n in deps) or "none")
        + ".\n"
        if "\nGitHub parent:" not in body
        else ""
    )
    state["issues"][i["key"]] = {
        **state["issues"].get(i["key"], {}),
        **ensure_issue(i["key"], f"[{i['key']}] {i['title']}", body, area, parent, deps),
    }
    save()
    print("Issue", i["key"], state["issues"][i["key"]]["url"], flush=True)
# Re-read native relationships before populating project metadata.
state["remote_issues"] = gh(
    "issue",
    "list",
    "--repo",
    REPO,
    "--state",
    "all",
    "--limit",
    "200",
    "--json",
    "number,title,url,parent,blockedBy,subIssues",
    decode=True,
)
save()
project_items = gh(
    "project",
    "item-list",
    number,
    "--owner",
    OWNER,
    "--limit",
    "200",
    "--format",
    "json",
    decode=True,
)["items"]
for sequence, obj in enumerate([*packet["epics"], *packet["issues"]]):
    key = obj["key"]
    row = state["epics" if key.startswith("E") else "issues"][key]
    item = next((x for x in project_items if x.get("content", {}).get("url") == row["url"]), None)
    if item is None:
        item = gh(
            "project",
            "item-add",
            number,
            "--owner",
            OWNER,
            "--url",
            row["url"],
            "--format",
            "json",
            decode=True,
        )
    row["item_id"] = item["id"]
    save()
    area = obj.get("area") or next(e["area"] for e in packet["epics"] if e["key"] == obj["epic"])
    values = {
        "Workflow": "Ready" if key == "G1" else "Backlog",
        "Status": "Todo",
        "Wave": f"Wave {obj.get('wave', 0)}",
        "Priority": obj.get("priority", "P1"),
        "Risk": obj.get("risk", "Medium"),
        "Area": area,
        "Persona": obj["personas"]
        if isinstance(obj["personas"], str)
        else ", ".join(obj["personas"]),
        "Sequence": sequence,
    }
    # Only initialize statuses once; reruns must not erase evidence-based progress.
    for name, value in values.items():
        if row.get("initialized") and name in ("Workflow", "Status"):
            continue
        f = state["fields"][name]
        args = [
            "project",
            "item-edit",
            "--id",
            item["id"],
            "--project-id",
            project["id"],
            "--field-id",
            f["id"],
        ]
        if "options" in f:
            option = next(x for x in f["options"] if x["name"] == value)
            args += ["--single-select-option-id", option["id"]]
        elif name == "Sequence":
            args += ["--number", value]
        else:
            args += ["--text", value]
        gh(*args)
    row["initialized"] = True
    save()
    print("Project item", key, flush=True)
state["verified_items"] = gh(
    "project",
    "item-list",
    number,
    "--owner",
    OWNER,
    "--limit",
    "200",
    "--format",
    "json",
    decode=True,
)
save()
print("Verified", len(state["verified_items"]["items"]), "items in", project["url"], flush=True)
