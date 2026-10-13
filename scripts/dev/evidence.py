"""Dispatch local evidence commands while keeping experiment outputs separate."""

import argparse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("performance", "status", "scaling", "recovery", "release")
    )
    parser.add_argument("--run-id", default="local")
    args, extra = parser.parse_known_args()
    if args.action in {"performance", "status", "scaling"}:
        from scripts.evidence.performance import main as performance

        action = "performance" if args.action == "status" else args.action
        return performance([action, "--run-id", args.run_id, *extra])
    if args.action == "recovery":
        if extra:
            parser.error("Recovery has no extra arguments")
        from scripts.evidence.recovery import run

        run(args.run_id)
        return 0
    from scripts.dev.release import main as release

    return release(["evidence", "--run-id", args.run_id, *extra])


if __name__ == "__main__":
    raise SystemExit(main())
