"""Runtime helper path handling that only breaks on a fresh virtual environment."""

import sys

from scripts.dev import v1_runtime


def test_moto_interpreter_keeps_the_venv_symlink_so_site_packages_stay_visible(
    tmp_path, monkeypatch
):
    # A venv's python is a symlink to the base interpreter; resolving it loses the venv.
    link = tmp_path / "venv-python"
    link.symlink_to(sys.executable)
    monkeypatch.setenv("V1_MOTO_PYTHON", str(link))
    assert v1_runtime.moto_python() == str(link)


def test_relative_moto_interpreter_is_made_absolute_without_following_links(tmp_path, monkeypatch):
    link = tmp_path / "venv-python"
    link.symlink_to(sys.executable)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("V1_MOTO_PYTHON", "venv-python")
    assert v1_runtime.moto_python() == str(tmp_path / "venv-python")
