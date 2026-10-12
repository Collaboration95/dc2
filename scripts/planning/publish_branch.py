"""Publish a local linear branch through authenticated gh; refuse history rewrites."""

import argparse
import base64
import json
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--repo", default="Collaboration95/dc2")
parser.add_argument("--base", default="Main")
args = parser.parse_args()


def git(*values):
    return subprocess.check_output(["git", *values])


def gh(endpoint, payload=None, method=None):
    command = ["gh", "api", "repos/" + args.repo + "/" + endpoint]
    if payload is not None:
        command += ["--method", method or "POST", "--input", "-"]
    return json.loads(
        subprocess.check_output(
            command, input=None if payload is None else json.dumps(payload).encode()
        )
    )


branch = git("branch", "--show-current").decode().strip()
if not branch:
    raise SystemExit("Refusing detached HEAD")
head = git("rev-parse", "HEAD").decode().strip()
branches = json.loads(
    subprocess.check_output(["gh", "api", f"repos/{args.repo}/git/matching-refs/heads/{branch}"])
)
ref = next((x for x in branches if x["ref"] == "refs/heads/" + branch), None)
if ref is None:
    base = gh("git/ref/heads/" + args.base)["object"]["sha"]
    subprocess.run(["git", "merge-base", "--is-ancestor", base, head], check=True)
    ref = gh("git/refs", {"ref": "refs/heads/" + branch, "sha": base})
remote = ref["object"]["sha"]
subprocess.run(["git", "merge-base", "--is-ancestor", remote, head], check=True)
commits = git("rev-list", "--reverse", remote + ".." + head).decode().splitlines()
for commit in commits:
    parents = git("show", "-s", "--format=%P", commit).decode().split()
    if len(parents) != 1:
        raise SystemExit("Publish reviewed linear commits only; integrate upstream locally first")
    parent = parents[0]
    changes = git(
        "diff-tree", "--no-commit-id", "--no-renames", "--raw", "-r", "-z", parent, commit
    ).split(b"\0")
    entries = []
    for i in range(0, len(changes) - 1, 2):
        header = changes[i].decode().split()
        path = changes[i + 1].decode()
        mode, sha, status = header[1], header[3], header[4]
        entry = {"path": path, "mode": mode, "type": "blob"}
        if status == "D":
            entry.update(mode=header[0][1:], sha=None)
            if entry["mode"] == "160000":
                entry["type"] = "commit"
        else:
            if mode == "160000":
                raise SystemExit("Unexpected submodule")
            data = git("cat-file", "blob", sha)
            try:
                content = data.decode("utf-8")
                if "\0" in content:
                    raise UnicodeError()
                entry["content"] = content
            except UnicodeError:
                blob = gh(
                    "git/blobs", {"content": base64.b64encode(data).decode(), "encoding": "base64"}
                )
                if blob["sha"] != sha:
                    raise SystemExit("Blob identity mismatch") from None
                entry["sha"] = sha
        entries.append(entry)
    tree = gh(
        "git/trees",
        {"base_tree": git("rev-parse", parent + "^{tree}").decode().strip(), "tree": entries},
    )
    if tree["sha"] != git("rev-parse", commit + "^{tree}").decode().strip():
        raise SystemExit("Tree identity mismatch")
    identity = (
        git("show", "-s", "--format=%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI", commit)
        .decode()
        .strip()
        .split("\0")
    )
    message = git("cat-file", "commit", commit).split(b"\n\n", 1)[1].decode()
    result = gh(
        "git/commits",
        {
            "tree": tree["sha"],
            "parents": [parent],
            "message": message,
            "author": dict(zip(["name", "email", "date"], identity[:3], strict=True)),
            "committer": dict(zip(["name", "email", "date"], identity[3:], strict=True)),
        },
    )
    if result["sha"] != commit:
        raise SystemExit("Commit identity mismatch")
    print("Uploaded", commit, flush=True)
if commits:
    result = gh("git/refs/heads/" + branch, {"sha": head, "force": False}, method="PATCH")
    if result["object"]["sha"] != head:
        raise SystemExit("Remote ref mismatch")
subprocess.run(["git", "update-ref", "refs/remotes/origin/" + branch, head], check=True)
print("Verified", branch, head)
