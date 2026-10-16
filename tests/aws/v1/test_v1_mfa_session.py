"""MFA session helper and the credential-kind guard, against a fake aws CLI; no AWS access."""

import configparser
import datetime as dt
import json
import stat
import subprocess
from pathlib import Path

import pytest

from scripts.aws.transport import OperationError
from scripts.aws.v1 import credentials, deploy, mfa_session

pytestmark = pytest.mark.unmeasured

SERIAL = "arn:aws:iam::866865534361:mfa/flickpond-guru"
SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
TOKEN = "IQoJb3JpZ2luX2VjEXAMPLETOKEN"
NOW = dt.datetime(2026, 10, 17, 12, 0, tzinfo=dt.UTC)
EXPIRY = "2026-10-19T00:00:00+00:00"


class FakeAws:
    """Answers the handful of calls mfa_session and the credential probe make."""

    def __init__(self, *, devices=None, code_ok=True, key="ASIAEXAMPLEKEY12345", account="1"):
        self.calls, self.payloads = [], []
        self.devices = [{"SerialNumber": SERIAL}] if devices is None else devices
        self.code_ok, self.key, self.account = code_ok, key, account

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if "--cli-input-json" in argv:
            path = Path(argv[argv.index("--cli-input-json") + 1].removeprefix("file://"))
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            self.payloads.append(json.loads(path.read_text()))
        words = [w for w in argv if not w.startswith("-")]
        if "list-mfa-devices" in argv:
            return done(argv, {"MFADevices": self.devices})
        if "get-session-token" in argv:
            if not self.code_ok:
                return done(argv, None, 254, "AccessDenied: MultiFactorAuthentication failed")
            return done(argv, {"Credentials": {
                "AccessKeyId": self.key, "SecretAccessKey": SECRET, "SessionToken": TOKEN,
                "Expiration": EXPIRY}})
        if "get-caller-identity" in argv:
            return done(argv, {"Account": "866865534361" if self.account == "1" else self.account})
        raise AssertionError(f"unexpected call {words}")


def done(argv, payload, code=0, err=""):
    return subprocess.CompletedProcess(argv, code, json.dumps(payload) if payload else "", err)


def run(tmp_path, *args, aws=None, capsys=None):
    aws = aws or FakeAws()
    code = mfa_session.main(["--code", "123456", *args], runner=aws, home=tmp_path, now=NOW)
    return code, aws


def parsed(path):
    parser = configparser.RawConfigParser()
    parser.read(path)
    return parser


def test_the_session_is_written_to_its_own_profile_with_a_region_and_private_mode(tmp_path):
    code, _ = run(tmp_path)
    assert code == 0
    creds = parsed(tmp_path / ".aws/credentials")["dc2-project2-mfa"]
    assert creds["aws_access_key_id"].startswith("ASIA")
    assert creds["aws_session_token"] == TOKEN
    config = parsed(tmp_path / ".aws/config")["profile dc2-project2-mfa"]
    assert config["region"] == "ap-southeast-1"
    for name in ("credentials", "config"):
        assert stat.S_IMODE((tmp_path / ".aws" / name).stat().st_mode) == 0o600


def test_only_the_expiry_is_printed_never_a_key_or_token(tmp_path, capsys):
    run(tmp_path)
    out = capsys.readouterr()
    text = out.out + out.err
    assert "2026-10-19T00:00:00Z" in text and "36.0 h" in text
    assert SECRET not in text and TOKEN not in text and "ASIA" not in text


def test_the_one_time_code_travels_in_a_private_file_not_the_argument_list(tmp_path):
    _, aws = run(tmp_path)
    assert all("123456" not in " ".join(call) for call in aws.calls)
    assert aws.payloads == [{"SerialNumber": SERIAL, "TokenCode": "123456",
                             "DurationSeconds": 129600}]


def test_the_serial_comes_from_the_base_profile_and_the_exchange_uses_that_profile(tmp_path):
    _, aws = run(tmp_path)
    assert aws.calls[0][:4] == ["aws", "--profile", "dc2-project2", "--region"]
    assert all(call[call.index("--profile") + 1] == "dc2-project2" for call in aws.calls)


def test_other_profiles_and_comments_in_the_credentials_file_survive_a_refresh(tmp_path):
    folder = tmp_path / ".aws"
    folder.mkdir()
    original = ("# my keys\n[default]\naws_access_key_id = AKIADEFAULT\n\n"
                "[dc2-project2]\naws_access_key_id = AKIALONGTERM\n")
    (folder / "credentials").write_text(original)
    run(tmp_path)
    run(tmp_path)  # a second mint replaces the first instead of duplicating it
    text = (folder / "credentials").read_text()
    assert text.startswith(original.rstrip("\n"))
    assert text.count("[dc2-project2-mfa]") == 1
    assert parsed(folder / "credentials")["dc2-project2"]["aws_access_key_id"] == "AKIALONGTERM"


def test_a_symlinked_credentials_file_stays_a_symlink(tmp_path):
    real = tmp_path / "dotfiles"
    real.mkdir()
    (real / "credentials").write_text("[default]\naws_access_key_id = AKIADEFAULT\n")
    folder = tmp_path / ".aws"
    folder.mkdir()
    (folder / "credentials").symlink_to(real / "credentials")
    run(tmp_path)
    assert (folder / "credentials").is_symlink()
    assert "dc2-project2-mfa" in (real / "credentials").read_text()


@pytest.mark.parametrize("args", [
    ["--profile", "default"], ["--base-profile", "default"], ["--profile", "dc2-project2"],
    ["--duration", "60"], ["--duration", "200000"], ["--account", "12"],
    ["--serial", "not-an-arn"],
])
def test_bad_scope_or_duration_is_refused_before_any_aws_call(tmp_path, args):
    aws = FakeAws()
    with pytest.raises(SystemExit):
        mfa_session.main(["--code", "123456", *args], runner=aws, home=tmp_path)
    assert aws.calls == []


@pytest.mark.parametrize("code", ["12345", "1234567", "abcdef", ""])
def test_a_malformed_code_is_refused_before_any_aws_call(tmp_path, code):
    aws = FakeAws()
    with pytest.raises(SystemExit):
        mfa_session.main(["--code", code], runner=aws, home=tmp_path)
    assert aws.calls == []


def test_a_user_with_no_device_or_several_is_a_refusal_not_a_guess(tmp_path, capsys):
    assert run(tmp_path, aws=FakeAws(devices=[]))[0] == 1
    two = [{"SerialNumber": SERIAL}, {"SerialNumber": SERIAL + "2"}]
    assert run(tmp_path, aws=FakeAws(devices=two))[0] == 1
    assert "pass --serial" in capsys.readouterr().err
    assert not (tmp_path / ".aws/credentials").exists()


def test_a_rejected_code_writes_nothing_and_does_not_echo_the_service_message(tmp_path, capsys):
    code, _ = run(tmp_path, aws=FakeAws(code_ok=False))
    assert code == 1
    assert "MultiFactorAuthentication" not in capsys.readouterr().err
    assert not (tmp_path / ".aws/credentials").exists()


def test_long_term_keys_returned_by_sts_are_refused(tmp_path):
    assert run(tmp_path, aws=FakeAws(key="AKIANOTASESSION1234"))[0] == 1
    assert not (tmp_path / ".aws/credentials").exists()


def test_the_account_check_confirms_the_new_session_resolves_to_the_expected_account(tmp_path):
    assert run(tmp_path, "--account", "866865534361")[0] == 0
    assert run(tmp_path, "--account", "111111111111")[0] == 1


# ---- credential kind -------------------------------------------------------------------
def exporter(key, *, token=True, expiration=None):
    data = {"Version": 1, "AccessKeyId": key, "SecretAccessKey": SECRET}
    if token:
        data["SessionToken"] = TOKEN
    if expiration:
        data["Expiration"] = expiration
    return lambda argv, **kw: subprocess.CompletedProcess(argv, 0, json.dumps(data), "")


def test_an_akia_key_is_classified_long_term_without_returning_it():
    info = credentials.probe("p", runner=exporter("AKIAEXAMPLE", token=False), environ={})
    assert info == {"kind": "long-term", "expires_at": None, "remaining_seconds": None}
    assert credentials.assess("p", info)[0] == "blocker"


def test_the_long_term_message_tells_the_operator_what_to_run():
    info = {"kind": "long-term", "expires_at": None, "remaining_seconds": None}
    detail = credentials.assess("dc2-project2", info)[1]
    assert "scripts.aws.v1.mfa_session" in detail and "dc2-project2-mfa" in detail


def test_an_asia_key_with_a_token_is_a_session_and_reports_its_remaining_time():
    runner = exporter("ASIAEXAMPLE", expiration="2026-10-17T14:00:00Z")
    info = credentials.probe("p", runner=runner, environ={}, now=NOW)
    assert info["kind"] == "session" and info["remaining_seconds"] == 7200
    assert credentials.assess("p", info)[0] == "pass"


def test_a_session_without_a_cli_expiry_falls_back_to_the_one_mfa_session_recorded(tmp_path):
    run(tmp_path)
    info = credentials.probe("dc2-project2-mfa", runner=exporter("ASIAEXAMPLE"), environ={},
                             home=tmp_path, now=NOW)
    assert info["expires_at"] == "2026-10-19T00:00:00Z"


def test_an_expired_or_nearly_expired_session_is_blocked_or_warned():
    for seconds, status in ((-5, "blocker"), (600, "warn"), (86400, "pass")):
        info = {"kind": "session", "expires_at": None, "remaining_seconds": seconds}
        assert credentials.assess("p", info)[0] == status


def test_an_unclassifiable_profile_is_a_warning_and_a_failed_export_is_unknown():
    failing = lambda argv, **kw: subprocess.CompletedProcess(argv, 253, "", "no profile")  # noqa: E731
    info = credentials.probe("p", runner=failing, environ={})
    assert info["kind"] == "unknown" and credentials.assess("p", info)[0] == "warn"


def test_require_mfa_session_raises_for_long_term_and_returns_the_info_otherwise():
    with pytest.raises(OperationError, match="mfa_session"):
        credentials.require_mfa_session("p", {"kind": "long-term", "expires_at": None,
                                              "remaining_seconds": None})
    ok = {"kind": "session", "expires_at": None, "remaining_seconds": None}
    assert credentials.require_mfa_session("p", ok) is ok


# ---- the deploy pipeline uses it -------------------------------------------------------------
def test_preflight_blocks_long_term_credentials_for_a_cloudformation_driven_deploy(tmp_path):
    from test_deploy import Rig

    rig = Rig(tmp_path)
    pipeline = rig.pipeline()
    pipeline.credential_probe = lambda _p: {"kind": "long-term", "expires_at": None,
                                            "remaining_seconds": None}
    with pytest.raises(deploy.DeployError, match="Preflight blockers: credentials"):
        pipeline.preflight()
    assert not any(deploy.is_mutating(op) for _, op, _ in rig.sim.calls)


def test_preflight_accepts_an_mfa_session_and_records_its_expiry(tmp_path):
    from test_deploy import Rig

    rig = Rig(tmp_path)
    pipeline = rig.pipeline()
    pipeline.credential_probe = lambda _p: {
        "kind": "session", "expires_at": "2026-10-19T00:00:00Z", "remaining_seconds": 90000}
    checks = {c["check"]: c for c in pipeline.preflight()["checks"]}
    assert checks["credentials"]["status"] == "pass"
    assert checks["credentials"]["expires_at"] == "2026-10-19T00:00:00Z"


def test_a_destructive_teardown_also_refuses_long_term_credentials(tmp_path):
    from test_deploy import Rig

    rig = Rig(tmp_path, confirm_run_id="t1")
    pipeline = rig.pipeline()
    pipeline.credential_probe = lambda _p: {"kind": "long-term", "expires_at": None,
                                            "remaining_seconds": None}
    with pytest.raises(deploy.DeployError, match="mfa_session"):
        pipeline.teardown()
    assert rig.sim.calls == []


def test_the_default_profile_is_still_refused_by_the_deploy_scope(tmp_path):
    from test_deploy import settings_for

    with pytest.raises(deploy.DeployError):
        settings_for(tmp_path, profile="default")
    assert settings_for(tmp_path, profile="dc2-project2-mfa").profile == "dc2-project2-mfa"
