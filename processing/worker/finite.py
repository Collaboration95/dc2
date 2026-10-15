"""Essential-container watchdog for the V1 SQS child (no legacy RQ entrypoint)."""

import argparse
import sys

from processing.worker.cloud import supervise


def main():
    parser = argparse.ArgumentParser(description="Watchdog for finite SQS encoders")
    parser.add_argument(
        "--deadline-epoch",
        "--deadline",
        "--cloud-deadline",
        dest="deadline",
        type=float,
        required=True,
    )
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--max-empty-polls", "--empty-polls", dest="empty_polls", type=int, default=2
    )
    args = parser.parse_args()
    raise SystemExit(
        supervise(
            [
                sys.executable,
                "-m",
                "processing.worker.sqs",
                "--deadline",
                str(args.deadline),
                "--name",
                args.name,
                "--empty-polls",
                str(args.empty_polls),
            ],
            end_epoch=args.deadline,
        )
    )


if __name__ == "__main__":
    main()
