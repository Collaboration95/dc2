"""Let an idle domain's minute ticks skip SQL, so Aurora can pause (V2-live, AD-27).

The repair schedules and the launcher tick every minute, and a tick that opens a database
connection keeps Aurora from ever reaching its 300 s auto-pause. Two SSM parameters per domain
decide, without SQL, whether a tick has anything to do:

* ``touched``: the time of the last request that may create pending SQL state. Every such
  writer (the Media API's mutating requests, the Media result consumer, the Processing command
  consumer) writes it BEFORE it commits.
* ``quiet``: ``"C T"``. The repair pass took the time C, then found, in SQL, that nothing is
  due before T (the same predicates its passes select by).

A tick skips SQL only while ``touched < C - MARGIN``, ``now < T`` and C is less than
MAX_QUIET_SECONDS old. Pending state is created either by a writer, which touched within
``MARGIN`` before its commit, so a commit that C's snapshot did not see has
``touched >= C - MARGIN``; or by time reaching a scheduled row (lease, retry, outbox replay,
cleanup rescan), whose time is at least T. Work that already exists (a running attempt, an
unsent row) makes the pass find something due now, and then it writes no quiet value at all.
Any read error, a missing or malformed value, is "not quiet".

The markers are best effort: a touch that cannot be written is logged and the request goes
ahead. Such a write may be missed until the quiet value ages out, so every tick runs a full SQL
pass at least every MAX_QUIET_SECONDS: work is found by the next minute's tick normally, and
within 30 minutes at worst.
"""

import logging
import math
import os
import time

from runtime_support.errors import log_safe_event

# A writer may reuse a touch for this long, and its invocation commits within the 60 s Lambda
# timeout of its last touch. MARGIN covers both with a minute of slack for clock skew and a
# put that lands after a later one.
REFRESH_SECONDS = 60
MARGIN_SECONDS = 180
# A quiet value older than this is ignored: the unconditional full sweep that bounds the delay
# a lost touch can cause.
MAX_QUIET_SECONDS = 30 * 60

logger = logging.getLogger(__name__)
_last_touch = {}  # parameter name -> when this container last wrote it


def _ssm_client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "ssm",
        region_name=os.environ.get("AWS_REGION"),
        config=Config(
            use_dualstack_endpoint=True,
            connect_timeout=2,
            read_timeout=3,
            retries={"mode": "standard", "total_max_attempts": 2},
        ),
    )


class Activity:
    def __init__(self, touched, quiet, *, client=None, clock=time.time):
        self.touched, self.quiet_name, self.clock = touched, quiet, clock
        self._client = client

    @classmethod
    def from_environ(cls, prefix, environ=None, **kwargs):
        """None unless the stack deployed the markers (the always-on environment only)."""
        environ = os.environ if environ is None else environ
        touched = environ.get(f"{prefix}_ACTIVITY_TOUCHED_PARAMETER")
        quiet = environ.get(f"{prefix}_ACTIVITY_QUIET_PARAMETER")
        return cls(touched, quiet, **kwargs) if touched and quiet else None

    @property
    def client(self):
        if self._client is None:
            self._client = _ssm_client()
        return self._client

    def _get(self, name):
        return self.client.get_parameter(Name=name)["Parameter"]["Value"]

    def _put(self, name, value):
        self.client.put_parameter(Name=name, Value=value, Type="String", Overwrite=True)

    def touch(self):
        """Record a write that is about to happen; never fails the request it belongs to."""
        now = self.clock()
        if now - _last_touch.get(self.touched, float("-inf")) < REFRESH_SECONDS:
            return
        try:
            self._put(self.touched, str(int(now)))
        except Exception as error:
            # The full sweep finds the write within MAX_QUIET_SECONDS; only the type is logged.
            log_safe_event(
                logger,
                level=logging.WARNING,
                event="activity_touch_failed",
                operation="activity_touch",
                error_class=type(error).__name__,
                outcome="full_sweep_required",
            )
            return
        _last_touch[self.touched] = now

    def quiet(self):
        """True only when SQL provably has nothing due; any doubt answers False."""
        try:
            touched = float(self._get(self.touched))
            checked, due = (float(v) for v in self._get(self.quiet_name).split())
        except Exception:
            return False
        if not all(math.isfinite(v) for v in (touched, checked, due)):
            return False
        now = self.clock()
        # A check from the future (or in milliseconds) is as untrustworthy as a stale one.
        return (
            touched < checked - MARGIN_SECONDS
            and now < due
            and 0 <= now - checked < MAX_QUIET_SECONDS
        )

    def record(self, checked_at, due_at):
        """After a pass: ``checked_at`` was taken before the SQL that found ``due_at``.

        ``due_at`` is the epoch of the earliest due item, or None if nothing is scheduled.
        Something due now writes nothing: the old value is already invalid (see the module
        docstring), and the next tick runs SQL either way. A failed write only costs SQL.
        """
        if due_at is not None and due_at <= checked_at:
            return
        due = min(due_at or float("inf"), checked_at + MAX_QUIET_SECONDS)
        try:
            self._put(self.quiet_name, f"{int(checked_at)} {int(due)}")
        except Exception as error:
            log_safe_event(
                logger,
                level=logging.WARNING,
                event="activity_quiet_write_failed",
                operation="activity_record",
                error_class=type(error).__name__,
                outcome="full_sweep_required",
            )
