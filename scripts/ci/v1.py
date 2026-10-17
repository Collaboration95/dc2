"""Use the shared policy for V1 image inputs and verify requested child jobs."""

import argparse
import json
import os
import subprocess

from scripts.ci.policy import changed_paths, classify


def validate(requested, needs):
    errors = []
    for job, enabled in requested.items():
        result = needs.get(job, {}).get("result", "missing")
        expected = "success" if enabled else "skipped"
        if result != expected:
            errors.append(f"{job}: requested={enabled}, result={result}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("images", "gate"))
    args = parser.parse_args()
    if args.action == "images":
        event = os.environ.get("EVENT")
        key = "PR_BASE" if event == "pull_request" else "PUSH_BEFORE"
        base = os.environ.get(key, "") if event in {"pull_request", "push"} else ""
        paths = None
        if base and set(base) != {"0"}:
            try:
                paths = changed_paths(base, "HEAD")
            except (subprocess.SubprocessError, UnicodeError):
                pass
        plan = classify(paths)
        selected = str(plan["selected"]["images"]).lower()
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            stream.write(f"changed={selected}\n")
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(f"V1 images selected: {selected}; shared CI input policy.\n")
        return
    needs = json.loads(os.environ["CI_NEEDS"])
    offline = os.environ["RUN_OFFLINE"] == "true"
    live = os.environ["RUN_LIVE"] == "true"
    forced = os.environ["IMAGES"] == "true"
    auto = os.environ.get("AUTO_IMAGES") == "true"
    selector = needs.get("image-paths", {})
    changed = selector.get("outputs", {}).get("changed")
    requested = {
        "v1-offline": offline,
        "v1-local": live,
        "image-paths": auto and not forced,
        "images": forced or (auto and changed == "true"),
    }
    errors = validate(requested, needs)
    if auto and not forced and changed not in {"true", "false"}:
        errors.append("image-paths did not supply a valid selection")
    if errors:
        raise SystemExit("\n".join(errors))
    print("V1 requested checks passed; only explicitly deselected jobs skipped")


if __name__ == "__main__":
    main()
