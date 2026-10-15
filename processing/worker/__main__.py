"""python -m processing.worker [--burst]."""

import argparse
import logging
import os
import stat

from processing.config import get_settings
from processing.queue import get_queue


def main():
    from rq import Worker

    parser = argparse.ArgumentParser(description="Processing attempt worker")
    parser.add_argument("--burst", action="store_true")
    parser.add_argument("--name", default=None)
    parser.add_argument("--cloud-deadline", type=float, default=None)
    parser.add_argument("--cloud-warm-fd", type=int, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.cloud_deadline is not None:
        from processing.worker.cloud import run

        if not args.name:
            parser.error("Cloud worker requires a correlated name")
        raise SystemExit(run(args.cloud_deadline, name=args.name, burst=args.burst))
    if args.cloud_warm_fd is not None:
        try:
            valid_pipe = (
                args.name
                and args.cloud_warm_fd >= 3
                and stat.S_ISFIFO(os.fstat(args.cloud_warm_fd).st_mode)
            )
        except OSError:
            valid_pipe = False
        if not valid_pipe:
            parser.error("Cloud child requires its parent watchdog pipe and correlated name")
    elif os.environ.get("PROCESSING_STORAGE_CREDENTIAL_MODE") == "ecs" or os.environ.get(
        "AWS_EXECUTION_ENV", ""
    ).startswith("AWS_ECS"):
        parser.error("Cloud worker requires an absolute watchdog deadline")
    # RQ includes the Redis connection URL at DEBUG; use INFO and no exception URLs.
    logging.basicConfig(level=logging.INFO)
    get_settings().require_worker()
    queue = get_queue()
    worker_class = Worker
    if args.cloud_warm_fd is not None:
        from processing.worker.cloud import finite_worker_class

        worker_class = finite_worker_class(args.cloud_warm_fd)
    kwargs = {"connection": queue.connection}
    if args.name is not None:
        kwargs["name"] = args.name
    worker_class([queue], **kwargs).work(burst=args.burst)


if __name__ == "__main__":
    main()
