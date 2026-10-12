"""python -m processing.worker [--burst]."""

import argparse
import logging

from processing.config import get_settings
from processing.queue import get_queue


def main():
    from rq import Worker

    parser = argparse.ArgumentParser(description="Processing attempt worker")
    parser.add_argument("--burst", action="store_true")
    args = parser.parse_args()
    # RQ includes the Redis connection URL at DEBUG; use INFO and no exception URLs.
    logging.basicConfig(level=logging.INFO)
    get_settings().require_worker()
    queue = get_queue()
    Worker([queue], connection=queue.connection).work(burst=args.burst)


if __name__ == "__main__":
    main()
