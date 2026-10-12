"""Offline regressions for browser acceptance assertions, not live UI evidence."""

import json
import shutil
import subprocess
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from scripts.dev.e2e_clients import (
    MEDIA_SAMPLE,
    BrowserMediaRequests,
    assert_video_progress,
    browser_login,
)


class ControlledLoginPage:
    def __init__(self, *, login_status=200, login_owner="owner"):
        self.login_status = login_status
        self.login_owner = login_owner
        self.registering = False
        self.signed_in = False
        self.fields = {}
        self.posts = []
        self.waits = []
        self.pending = None

    @contextmanager
    def expect_response(self, predicate):
        response = SimpleNamespace(value=None)
        self.pending = (predicate, response)
        yield response
        assert response.value is not None, "No matching POST reached the response waiter"
        self.pending = None

    def locator(self, selector):
        def click():
            if selector == "#auth-toggle":
                self.registering = not self.registering
                return
            if selector == "#logout":
                route, status, owner = "logout", 204, None
                self.signed_in = False
            else:
                assert selector == "#auth-submit"
                assert self.fields == {
                    "#auth-email": "existing@example.test",
                    "#auth-password": "existing-credentials",
                }
                route = "register" if self.registering else "login"
                status = 201 if self.registering else self.login_status
                owner = "owner" if self.registering else self.login_owner
                self.signed_in = status in (200, 201)
            self.posts.append(route)
            reply = SimpleNamespace(
                url=f"https://controlled.invalid/api/auth/{route}",
                request=SimpleNamespace(method="POST"),
                status=status,
                json=lambda: {"id": owner},
            )
            predicate, response = self.pending
            assert not predicate(
                SimpleNamespace(url=reply.url, request=SimpleNamespace(method="GET"))
            )
            if predicate(reply):
                response.value = reply

        def wait_for(*, state):
            self.waits.append((selector, state, tuple(self.posts)))
            visible = self.signed_in if selector == "#app" else not self.signed_in
            assert visible == (state == "visible")

        return SimpleNamespace(
            click=click, fill=lambda value: self.fields.update({selector: value}), wait_for=wait_for
        )


def test_ui_login_requires_logout_then_existing_credentials_post_and_visible_app():
    page = ControlledLoginPage()
    records = []
    scenario = SimpleNamespace(record=lambda event, **values: records.append((event, values)))
    browser_login(page, scenario, "existing@example.test", "existing-credentials")
    assert page.posts == ["register", "logout", "login"]
    assert ("#app", "hidden", ("register", "logout")) in page.waits
    assert page.waits[-1] == ("#app", "visible", ("register", "logout", "login"))
    assert records == [
        ("browser-ui-login", {"register_status": 201, "logout_status": 204, "login_status": 200})
    ]
    assert "existing-credentials" not in str(records)


@pytest.mark.parametrize("status,owner", [(401, "owner"), (200, "different-owner")])
def test_registration_success_cannot_hide_broken_browser_login(status, owner):
    page = ControlledLoginPage(login_status=status, login_owner=owner)
    records = []
    with pytest.raises(AssertionError):
        browser_login(
            page,
            SimpleNamespace(record=lambda *a, **kw: records.append(a)),
            "existing@example.test",
            "existing-credentials",
        )
    assert not records
    assert page.posts == ["register", "logout", "login"]


def response(url, *, text="", body=b"segment", status=200, redirected_from=None):
    return SimpleNamespace(
        url=url,
        status=status,
        text=lambda: text,
        body=lambda: body,
        request=SimpleNamespace(url=url, redirected_from=redirected_from),
    )


def ladder():
    media = BrowserMediaRequests()
    root = "https://controlled.invalid/api/jobs/asset/hls/master.m3u8"
    child = "https://controlled.invalid/api/jobs/asset/hls/720/index.m3u8"
    segment = "https://storage.invalid/asset/segment.ts?X-Amz-Signature=never-persist"
    media.seen(response(root, text="#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100\n720/index.m3u8"))
    media.seen(response(child, text=f"#EXTM3U\n#EXTINF:2\n{segment}\n#EXT-X-ENDLIST"))
    return media, root, segment


def test_browser_hls_requires_successful_matching_manifest_and_nonempty_segment():
    media, root, segment = ladder()
    media.seen(response(segment))
    assert media.counts(root) == {"playlists": 2, "segments": 1}
    assert "never-persist" not in str(media.counts(root))


def test_browser_hls_segment_redirect_matches_playlist_reference():
    media = BrowserMediaRequests()
    root = "https://controlled.invalid/api/jobs/asset/hls/index.m3u8"
    facade = "https://controlled.invalid/api/jobs/asset/hls/segment.ts"
    media.seen(response(root, text="#EXTM3U\n#EXTINF:2\nsegment.ts"))
    media.seen(
        response(
            "https://storage.invalid/segment.ts?X-Amz-Signature=never-persist",
            redirected_from=SimpleNamespace(url=facade, redirected_from=None),
        )
    )
    assert media.counts(root) == {"playlists": 1, "segments": 1}


@pytest.mark.parametrize("failure", ["missing", "unrelated", "empty", "failed-http"])
def test_hls_manifest_alone_or_unrelated_segment_cannot_pass(failure):
    media, root, segment = ladder()
    if failure == "unrelated":
        media.seen(response("https://storage.invalid/different/segment.ts"))
    elif failure == "empty":
        media.seen(response(segment, body=b""))
    elif failure == "failed-http":
        media.seen(response(segment, status=403))
    with pytest.raises(AssertionError):
        media.counts(root)


def sample(**changes):
    return {
        "ready": 4,
        "error": None,
        "current_time": 0,
        "decoded_frames": 0,
        "selected_hls": True,
        "selected_mp4": False,
        "source_kind": "blob",
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"selected_hls": False, "selected_mp4": True, "source_kind": "mp4"},
        {"decoded_frames": 0},
        {"current_time": 0},
        {"ready": 1},
        {"error": 3},
    ],
)
def test_hls_gate_rejects_mp4_fallback_clock_only_progress_and_decoder_failure(changes):
    with pytest.raises(AssertionError):
        assert_video_progress(
            sample(), sample(**{"current_time": 0.3, "decoded_frames": 5, **changes}), "hls"
        )


@pytest.mark.parametrize("kind", ["blob", "native-hls"])
def test_hls_gate_accepts_selected_advancing_decoded_video(kind):
    assert_video_progress(
        sample(source_kind=kind),
        sample(current_time=0.3, decoded_frames=5, source_kind=kind),
        "hls",
    )


def test_mp4_gate_requires_explicit_mp4_selection():
    with pytest.raises(AssertionError):
        assert_video_progress(sample(), sample(current_time=0.3, decoded_frames=5), "mp4")
    assert_video_progress(
        sample(selected_hls=False, selected_mp4=True),
        sample(
            current_time=0.3,
            decoded_frames=5,
            selected_hls=False,
            selected_mp4=True,
            source_kind="mp4",
        ),
        "mp4",
    )


@pytest.mark.parametrize(
    "source,hls_supported,native,kind",
    [
        ("blob:controlled", True, False, "blob"),
        ("https://controlled.invalid/ladder.m3u8", False, True, "native-hls"),
        ("https://storage.invalid/primary.mp4?signature=never-persist", True, True, "mp4"),
        ("blob:controlled", False, False, "other"),
    ],
)
def test_actual_media_sample_javascript_classifies_source_without_returning_capabilities(
    source,
    hls_supported,
    native,
    kind,
):
    # Execute the exact sampling JS against controlled plain objects, with no
    # DOM, browser or network. This is assertion logic evidence only.
    node = shutil.which("node")
    assert node, "Offline JS regression needs the existing frontend Node runtime"
    expected = {
        "hls": "/ladder.m3u8",
        "mp4": "https://storage.invalid/primary.mp4?signature=never-persist",
    }
    code = (
        "global.location={href:'https://controlled.invalid/'};"
        f"global.window={{Hls:{{isSupported:()=>{json.dumps(hls_supported)}}}}};"
        f"const v={{currentSrc:{json.dumps(source)},canPlayType:()=>{json.dumps(native)},"
        "readyState:4,currentTime:0.3,error:null,"
        "getVideoPlaybackQuality:()=>({totalVideoFrames:5})};"
        f"process.stdout.write(JSON.stringify(({MEDIA_SAMPLE})(v,{json.dumps(expected)})));"
    )
    result = subprocess.run(
        [node, "-e", code], check=True, capture_output=True, text=True, timeout=5
    )
    state = json.loads(result.stdout)
    assert state["source_kind"] == kind
    assert state["selected_hls"] == (kind in {"blob", "native-hls"})
    assert state["selected_mp4"] == (kind == "mp4")
    assert state["decoded_frames"] == 5
    assert "never-persist" not in result.stdout and "https://" not in result.stdout
