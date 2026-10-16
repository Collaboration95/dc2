"""Small synchronous Lambda bridges; dependencies are injectable in async APIs."""

import os
import time


def deadline_for(context, *, maximum=20):
    remaining = (
        context.get_remaining_time_in_millis() / 1000 - 1
        if context is not None and hasattr(context, "get_remaining_time_in_millis")
        else maximum
    )
    return time.monotonic() + max(0.01, min(maximum, remaining))


def queue_urls():
    return {
        name: os.environ.get(env, "")
        for name, env in (
            ("processing-commands", "PROCESSING_COMMANDS_QUEUE_URL"),
            ("processing-work", "PROCESSING_WORK_QUEUE_URL"),
            ("media-results", "MEDIA_RESULTS_QUEUE_URL"),
        )
    }
