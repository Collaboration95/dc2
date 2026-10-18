import pytest

from scripts.dev import v1_runtime


def test_moto_python_prefers_the_checkouts_own_pinned_environment(tmp_path, monkeypatch):
    python = tmp_path / v1_runtime.MOTO_VENV / "bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.delenv("V1_MOTO_PYTHON", raising=False)
    monkeypatch.setattr(v1_runtime, "ROOT", tmp_path)
    assert v1_runtime.moto_python() == str(python)


def test_explicit_moto_python_wins_over_the_checkout_environment(monkeypatch):
    monkeypatch.setenv("V1_MOTO_PYTHON", "/tmp/custom/bin/python")
    assert v1_runtime.moto_python() == "/tmp/custom/bin/python"


def test_missing_moto_environment_points_at_the_setup_target(tmp_path, monkeypatch):
    monkeypatch.delenv("V1_MOTO_PYTHON", raising=False)
    monkeypatch.setattr(v1_runtime, "ROOT", tmp_path)
    monkeypatch.setattr(v1_runtime, "run", lambda *a, **k: type("R", (), {"stdout": "x"})())
    with pytest.raises(ValueError, match="make setup-v1"):
        v1_runtime.moto_python()


def test_moto_pin_matches_the_ci_workflow():
    workflow = (v1_runtime.ROOT / ".github/workflows/v1.yml").read_text()
    assert v1_runtime.MOTO_REQUIREMENT in workflow
