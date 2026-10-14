import json
import stat

import pytest
from test_transport_fixtures import clock as clock
from test_transport_fixtures import config as config
from test_transport_fixtures import fake as fake
from test_transport_fixtures import journal as journal

from scripts.aws.journal import Journal
from scripts.aws.transport import OperationError


def test_private_atomic_restart(journal):
    assert stat.S_IMODE(journal.path.stat().st_mode) == 0o600
    with journal.locked() as state:
        state["paused"] = True
        journal.save(state)
    restarted = Journal(journal.path, station="station-a", environment="demo")
    with restarted.locked() as state:
        assert state["paused"] is True
    assert not list(journal.path.parent.glob(".intent-*"))


def test_busy_and_wrong_station(journal):
    with journal.locked():
        with pytest.raises(OperationError, match="busy"), journal.locked():
            pass
    wrong = Journal(journal.path, station="station-b", environment="demo")
    with pytest.raises(OperationError, match="station"), wrong.locked():
        pass


def test_missing_corrupt_and_public_journal(journal):
    journal.path.write_text("invalid")
    with pytest.raises(OperationError, match="invalid"), journal.locked():
        pass
    journal.path.unlink()
    with pytest.raises(OperationError, match="Missing"), journal.locked():
        pass
    journal.path.parent.chmod(0o755)
    with pytest.raises(OperationError, match="private"), journal.locked():
        pass


def test_secrets_fail_without_overwriting(journal):
    original = journal.path.read_bytes()
    with journal.locked() as state:
        state["cookie"] = "PRIVATE-DUMMY"
        with pytest.raises(OperationError):
            journal.save(state)
    assert journal.path.read_bytes() == original


def test_handover_needs_quiescence_and_cannot_replace(journal):
    with pytest.raises(OperationError, match="handover"):
        journal.initialize(verified_empty=False, exclusive_station=True)
    with pytest.raises(OperationError, match="replaced"):
        journal.initialize(verified_empty=True, exclusive_station=True)


def test_symlink_refused(journal, tmp_path):
    target = tmp_path / "other"
    target.write_text(json.dumps({"version": 1}))
    journal.path.unlink()
    journal.path.symlink_to(target)
    with pytest.raises(OperationError), journal.locked():
        pass


def test_station_lock_excludes_another_local_process(journal):
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    code = """import sys
from scripts.aws.journal import Journal
from scripts.aws.transport import OperationError
try:
    with Journal(sys.argv[1], station='station-a', environment='demo').locked():
        raise SystemExit(2)
except OperationError:
    print('busy')
"""
    with journal.locked():
        result = subprocess.run(
            [sys.executable, "-c", code, str(journal.path)],
            env={"PYTHONPATH": str(root)},
            cwd=root,
            text=True,
            capture_output=True,
            timeout=5,
            check=True,
        )
    assert result.stdout.strip() == "busy"
