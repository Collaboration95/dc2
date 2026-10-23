"""Demo recording tools (scripts/demo): the D5 report, the D4 fixtures and the warm-up.

Offline. The report's input is produced by the real generator (`generator.run`) with an injected
request, clock and sleep, so the DC2-RESULT and DC2-SAMPLES lines are the generator's own
encoding; only the network is replaced.
"""

import json
import re
import struct
from pathlib import Path

import pytest

from scripts.aws.v1.proof import generator
from scripts.demo import fixtures, perf_report, warmup

ROOT = Path(__file__).resolve().parents[2]
RECEIPT = ROOT / "docs/results/engineering-20261021/short-lane-sl1021.json"
CONFIG = {"users": 4, "seconds": 10, "warmup": 2, "other_seconds": 2, "logins": 3}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(0.0, seconds)


def fake_request(user, method, path, cookie=None, body=None):
    """Status: 100 + 10*user ms. /auth/me: user 0 is throttled (429). Login: 1500 ms."""
    if path == "/api/media/auth/register":
        return 201, 50.0, [], b""
    if path == "/api/media/auth/login":
        return 200, 1500.0, ["session=s; HttpOnly; Secure"], b""
    if path == generator.STATUS_ROUTE:
        return 200, 100.0 + 10 * user, [], b""
    if path == "/api/media/auth/me" and user == 0:
        return 429, 5.0, [], b""
    return 200, 20.0, [], b""


def generator_log(capsys, request=fake_request):
    clock, lines = Clock(), []

    def emit(marker, payload):
        print(f"{marker} {json.dumps(payload, sort_keys=True)}", flush=True)

    code = generator.run(CONFIG, request, clock, clock.sleep, emit)
    lines.append(capsys.readouterr().out)
    return code, "".join(lines)


@pytest.fixture
def run_dir(tmp_path, capsys):
    code, text = generator_log(capsys)
    assert code == 0
    folder = tmp_path / "perf-20261024T100000Z"
    folder.mkdir()
    (folder / "generator.log").write_text("noise before the run\n" + text)
    return folder


def cell(page, label):
    """The cells of the table row whose first cell starts with `label`."""
    for row in re.findall(r"<tr>(.*?)</tr>", page, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if cells and cells[0].startswith(label):
            return cells
    raise AssertionError(f"no row {label!r}")


# ---- perf_report ------------------------------------------------------------------------------
def test_report_recomputes_figures_from_the_generator_samples(run_dir):
    page, data = perf_report.build(run_dir, reference=None)
    # 10 rounds x 4 users: 100/110/120/130 ms ten times each; nearest rank p50 = 20th, p90 = 36th.
    assert cell(page, "status")[1:] == ["40", "0", "0", "110.0", "130.0", "130.0", "130.0", "130.0"]
    assert cell(page, "login")[1:4] == ["3", "0", "0"]
    assert cell(page, "/api/media/auth/me")[1:4] == ["20", "2", "2"]
    assert cell(page, "Status route p90")[2:] == ["130.0 ms", "PASS"]
    assert cell(page, "Login p90")[2:] == ["1500.0 ms", "PASS"]
    # 40 status + 4 routes x 2 rounds x 10 users + 3 logins = 123 timed; the two 429s count.
    assert cell(page, "Error rate")[2:] == ["1.63% (2 of 123)", "MISS"]
    assert data["agree"] and "agree with the DC2-RESULT summary" in page
    assert "4 virtual users reading the status route once a second for 10 s after a 2 s" in page
    assert "Lane comparison" not in page and "not recorded (no environment.json)" in page


def test_report_is_self_contained(run_dir):
    page, _ = perf_report.build(run_dir, lane_receipt=RECEIPT)
    lowered = page.lower()
    for needle in ("<script", "src=", "href=", "<link", "url(", "@import", "http://", "https://"):
        assert needle not in lowered, needle
    assert page.count("<svg") == page.count("</figure>") == 3


def test_report_reads_environment_and_lane_receipt(run_dir):
    (run_dir / "environment.json").write_text(
        json.dumps(
            {
                "started_utc": "2026-10-24T10:00:00Z",
                "ended_utc": "2026-10-24T10:02:00Z",
                "base_url": "api.example.test",
                "commit": "abc123",
                "stage_throttle": {"ThrottlingRateLimit": 20, "ThrottlingBurstLimit": 50},
            }
        )
    )
    page, _ = perf_report.build(run_dir, lane_receipt=RECEIPT)
    assert "2026-10-24T10:00:00Z to 2026-10-24T10:02:00Z" in page and "abc123" in page
    assert "stage limit 20 req/s" in page and "20 req/s, burst 50" in page
    assert cell(page, "Short lane (Lambda)")[1:4] == ["5 / 0", "0.26 s", "2.58 s"]
    assert cell(page, "Standard lane (Fargate)")[2] == "32.6 s"
    assert cell(page, "Short-lane median queue wait")[1:] == ["&lt;= 20 s", "0.26 s", "PASS"]
    assert "short-lane-sl1021.json" in page


def test_reference_row_is_read_from_the_committed_evidence(run_dir):
    page, _ = perf_report.build(run_dir)
    assert cell(page, "Reference only")[2:] == ["58.2 ms", "PASS"]


def test_tampered_samples_stop_the_render(run_dir):
    log = run_dir / "generator.log"
    text = log.read_text()
    result = json.loads(re.search(r"^DC2-RESULT (.*)$", text, re.M)[1])
    result["samples_sha256"] = "0" * 64
    log.write_text(re.sub(r"^DC2-RESULT .*$", "DC2-RESULT " + json.dumps(result), text, flags=re.M))
    with pytest.raises(perf_report.ReportError, match="SHA-256"):
        perf_report.build(run_dir)


def test_failed_generator_and_missing_chunks_are_refused(tmp_path, capsys):
    def asleep(user, method, path, cookie=None, body=None):
        return 503, 10000.0, [], b""

    code, text = generator_log(capsys, asleep)
    assert code == 1
    with pytest.raises(perf_report.ReportError, match="stage 'register'"):
        perf_report.load_run(text)
    _, good = generator_log(capsys)
    without_samples = "\n".join(x for x in good.splitlines() if not x.startswith("DC2-SAMPLES"))
    with pytest.raises(perf_report.ReportError, match="cannot be decoded"):
        perf_report.load_run(without_samples)


def test_cli_writes_the_report(run_dir, capsys):
    assert perf_report.main(["--run-dir", str(run_dir)]) == 0
    assert (run_dir / "report.html").read_text().startswith("<!doctype html>")
    assert "status p90 130.0 ms" in capsys.readouterr().out
    assert perf_report.main(["--run-dir", str(run_dir / "missing")]) == 2


# ---- fixtures ---------------------------------------------------------------------------------
def box(kind, payload):
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "short24.mp4"
    path.write_bytes(
        box(b"ftyp", b"isom\0\0\2\0isomiso2avc1mp41")
        + box(b"free", b"")
        + box(b"mdat", b"\x01" * 4096)
        + box(b"moov", b"\x02" * 512)
    )
    return path


def test_standard_fixtures_cross_the_lane_bound_and_stay_valid(source, tmp_path):
    made = fixtures.make(source, tmp_path / "out", lane="standard", count=2)
    assert [p.relative_to(tmp_path / "out").as_posix() for p in made] == [
        "standard-1/short24-standard-1.mp4",
        "standard-2/short24-standard-2.mp4",
    ]
    original = source.read_bytes()
    digests = set()
    for path in made:
        size = path.stat().st_size
        assert fixtures.MAX_SOURCE_BYTES < size < fixtures.MAX_UPLOAD_BYTES
        found = fixtures.check_mp4(path)
        assert [k for k, _, _ in found] == ["ftyp", "free", "mdat", "moov", "free"]
        assert found[-1][2] == 70 * fixtures.MIB + 8 and sum(s for _, _, s in found) == size
        with path.open("rb") as stream:
            assert stream.read(len(original)) == original  # streams untouched
            digests.add(stream.read(200))
    assert len(digests) == 2  # distinct bytes, so distinct hashes


def test_short_fixtures_stay_under_the_bound_and_differ(source, tmp_path):
    made = fixtures.make(source, tmp_path / "out", lane="short", count=3)
    assert len({p.read_bytes() for p in made}) == 3
    for path in made:
        assert path.stat().st_size == source.stat().st_size + 8 + 64
        assert fixtures.check_mp4(path)[-1][0] == "free"


def test_fixture_bounds_and_malformed_sources_are_refused(source, tmp_path):
    with pytest.raises(fixtures.FixtureError, match="standard-lane window"):
        fixtures.make(source, tmp_path / "a", lane="standard", count=1, pad_mib=40)
    with pytest.raises(fixtures.FixtureError, match="standard-lane window"):
        fixtures.make(source, tmp_path / "b", lane="standard", count=1, pad_mib=100)
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(source.read_bytes()[:-10])
    with pytest.raises(fixtures.FixtureError, match="invalid size"):
        fixtures.make(broken, tmp_path / "c", lane="short", count=1)
    not_mp4 = tmp_path / "x.mp4"
    not_mp4.write_bytes(box(b"mdat", b"\0" * 16))
    with pytest.raises(fixtures.FixtureError, match="ftyp"):
        fixtures.check_mp4(not_mp4)


# ---- warm-up ----------------------------------------------------------------------------------
def test_warmup_retries_until_both_databases_answer(capsys):
    clock = Clock()
    calls = []
    waking = {"login": 2, "processing": 1}  # 503s before each database answers

    def http(method, url, headers, body, timeout):
        path = url.split("example.test", 1)[1]
        calls.append((method, path))
        if path.endswith("/health"):
            service = path.split("/")[2]
            data = {"status": "ok", "service": service, "schema_version": 1}
            return 200, {}, json.dumps(data).encode()
        if path == "/api/media/jobs" and "cookie" not in headers:
            return 401, {}, b""
        if path == "/api/media/auth/login":
            if waking["login"]:
                waking["login"] -= 1
                return 503, {}, b""
            cookie = "session=s; Path=/; HttpOnly; Secure; SameSite=Strict"
            return 200, {"set-cookie": [cookie]}, b'{"id": "u"}'
        if path == "/api/media/jobs":
            return 200, {}, b"[]"
        if path.startswith("/api/processing/jobs?asset_ids="):
            if waking["processing"]:
                waking["processing"] -= 1
                return 503, {}, b""
            return 200, {}, b"[]"
        raise AssertionError(path)

    creds = {"email": "a@example.test", "password": "pw-not-printed"}
    ok = warmup.warm("https://example.test", creds, http=http, clock=clock, sleep=clock.sleep)
    out = capsys.readouterr().out
    assert ok and "login [503, 503, 200], processing [503, 200]" in out
    assert "pw-not-printed" not in out and "a@example.test" not in out
    assert all(method in {"GET", "POST"} for method, _ in calls)
    assert not any("reservations" in path for _, path in calls)  # read-only


def test_warmup_credentials_come_from_environment_or_prompt():
    env = {"DEMO_EMAIL": "a@example.test", "DEMO_PASSWORD": "pw"}
    assert warmup.credentials(env) == {"email": "a@example.test", "password": "pw"}
    asked = warmup.credentials({}, ask=lambda _: " b@example.test ", secret=lambda _: "pw2")
    assert asked == {"email": "b@example.test", "password": "pw2"}
