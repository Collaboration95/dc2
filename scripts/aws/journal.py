"""One designated operator station, private atomic intent, no launch database."""

import fcntl
import json
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

from scripts.aws.transport import OperationError, config_value, safe_record


class Journal:
    def __init__(self, path, *, station, environment):
        self.path = Path(path)
        self.station, self.environment = station, environment

    def check_context(self, config):
        if (
            config_value(config, "operator_station") != self.station
            or config_value(config, "environment_id") != self.environment
        ):
            raise OperationError("Config does not designate this station/environment")

    def _directory(self):
        directory = self.path.parent
        if directory.is_symlink() or not directory.is_dir():
            raise OperationError("Private journal directory must exist")
        if directory.stat().st_uid != os.geteuid() or directory.stat().st_mode & 0o077:
            raise OperationError("Journal directory must be private (0700)")

    def initialize(self, *, verified_empty, exclusive_station):
        """Explicit bootstrap/handover only after operator-proven empty inventory.

        No automatic initialization on a missing/corrupt journal. This evidence is
        supplied by the authorized station; it is not cross-station consensus.
        """
        self._directory()
        if verified_empty is not True or exclusive_station is not True:
            raise OperationError("Quiescent exclusive handover required")
        with self._lock():
            if self.path.exists() or self.path.is_symlink():
                raise OperationError("Existing journal must not be replaced")
            self.save(
                {
                    "version": 1,
                    "station": self.station,
                    "environment": self.environment,
                    "launches": {},
                    "paused": True,
                    "pending_release": None,
                    "session": "closed",
                }
            )

    @contextmanager
    def _lock(self):
        self._directory()
        fd = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            if stat.S_IMODE(os.fstat(fd).st_mode) != 0o600:
                raise OperationError("Unsafe lock permissions")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise OperationError("Operator station already busy") from None
            yield
        finally:
            os.close(fd)

    @contextmanager
    def locked(self):
        with self._lock():
            try:
                fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd) as handle:
                    if (
                        os.fstat(handle.fileno()).st_uid != os.geteuid()
                        or stat.S_IMODE(os.fstat(handle.fileno()).st_mode) != 0o600
                    ):
                        raise OperationError("Unsafe journal permissions")
                    state = json.load(handle)
                if (
                    state["version"] != 1
                    or state["station"] != self.station
                    or state["environment"] != self.environment
                ):
                    raise OperationError("Unknown station or journal version")
                safe_record(state)
                if not isinstance(state["launches"], dict):
                    raise OperationError("Invalid reservations")
            except (OSError, ValueError, KeyError, TypeError):
                raise OperationError(
                    "Missing or invalid journal; explicit handover required"
                ) from None
            yield state

    def save(self, state):
        safe_record(state)
        self._directory()
        fd, temporary = tempfile.mkstemp(prefix=".intent-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(state, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
