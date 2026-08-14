from __future__ import annotations

import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import requests

from archive_kindle_cli import fetch as F

SNAPSHOT_BODY = "<html><head><title>Mock</title></head><body><h1>Hi</h1></body></html>"


class _Handler(BaseHTTPRequestHandler):
    hits: dict = {"home": 0, "snap": 0}

    def do_GET(self):  # noqa: N802
        if self.path == "/":
            self.hits["home"] += 1
            self.send_response(200)
            self.send_header("Set-Cookie", "qki=mockcookie; Path=/")
            self.end_headers()
            self.wfile.write(b"<html><body>home</body></html>")
        elif self.path == "/Pxjvq":
            self.hits["snap"] += 1
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(SNAPSHOT_BODY.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):  # noqa: A003
        pass


@pytest.fixture
def mock_archive(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    orig_get = requests.Session.get

    def routed(self, url, *args, **kwargs):
        if url.startswith("https://archive.ph"):
            url = f"http://127.0.0.1:{port}" + url[len("https://archive.ph"):]
        return orig_get(self, url, *args, **kwargs)

    monkeypatch.setattr(requests.Session, "get", routed)
    yield server
    server.shutdown()


# --- normalize_url ---------------------------------------------------------


def test_normalize_mirror_urls():
    assert F.normalize_url("https://archive.is/Pxjvq") == "https://archive.ph/Pxjvq"
    assert F.normalize_url("archive.today/AbCdE") == "https://archive.ph/AbCdE"
    assert F.normalize_url("Pxjvq") == "https://archive.ph/Pxjvq"
    assert F.normalize_url("  https://archive.ph/xyz#frag ") == "https://archive.ph/xyz"


def test_normalize_rejects_non_archive():
    with pytest.raises(F.FetchError):
        F.normalize_url("https://example.com/not-archive")
    with pytest.raises(F.FetchError):
        F.normalize_url("not a url at all !!")


# --- challenge detection ----------------------------------------------------


def test_is_challenge_status_codes():
    assert F._is_challenge(429, "<html>hi</html>")
    assert F._is_challenge(403, "<html>hi</html>")
    assert not F._is_challenge(200, "<html>hi</html>")


def test_is_challenge_body_markers():
    assert F._is_challenge(200, '<html><div id="g-recaptcha"></div></html>')
    assert F._is_challenge(200, "<html>One more step</html>")
    assert F._is_challenge(200, "<html>please complete the security check</html>")
    assert not F._is_challenge(200, "<html>a normal page</html>")


# --- fetch_snapshot ---------------------------------------------------------


def test_fetch_happy_path_persists_cookies(mock_archive, cache_dir):
    body = F.fetch_snapshot("Pxjvq", cache_dir, timeout=10)
    assert body == SNAPSHOT_BODY
    assert _Handler.hits["home"] == 1 and _Handler.hits["snap"] == 1
    jar = (cache_dir / "cookies.txt").read_text()
    assert "qki" in jar


def test_fetch_retries_after_transient_429(mock_archive, cache_dir, monkeypatch):
    _Handler.hits["snap"] = 0
    orig = _Handler.do_GET

    def flaky(self):
        if self.path == "/Pxjvq" and _Handler.hits["snap"] == 0:
            _Handler.hits["snap"] += 1
            self.send_response(429)
            self.end_headers()
            self.wfile.write(b"blocked")
        else:
            orig(self)

    monkeypatch.setattr(_Handler, "do_GET", flaky)
    body = F.fetch_snapshot("Pxjvq", cache_dir, timeout=10)
    assert body == SNAPSHOT_BODY
    assert _Handler.hits["snap"] == 2


def test_fetch_raises_captcha_blocked(mock_archive, cache_dir, monkeypatch):
    def always_block(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(
            b'<html><body><div id="g-recaptcha"></div>One more step</body></html>'
        )

    monkeypatch.setattr(_Handler, "do_GET", always_block)
    with pytest.raises(F.CaptchaBlocked):
        F.fetch_snapshot("Pxjvq", cache_dir, timeout=10)


def test_fetch_rejects_bad_input(cache_dir):
    with pytest.raises(F.FetchError):
        F.fetch_snapshot("https://example.com/x", cache_dir)


# --- browser fallback -------------------------------------------------------


class FakePage:
    def __init__(self, html):
        self._html = html

    def goto(self, *a, **k):
        pass

    def content(self):
        return self._html


class FakeContext:
    def __init__(self, html):
        self._html = html
        self.pages = [FakePage(html)]

    def new_page(self):
        page = FakePage(self._html)
        self.pages.append(page)
        return page

    def cookies(self):
        return []


class FakeChromium:
    def __init__(self, html):
        self._html = html

    def launch_persistent_context(self, **kwargs):
        return FakeContext(self._html)


class FakePlaywright:
    def __init__(self, html):
        self.chromium = FakeChromium(html)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def _install_fake_playwright(monkeypatch, html):
    sync_api = SimpleNamespace(sync_playwright=lambda: FakePlaywright(html))
    monkeypatch.setitem(sys.modules, "playwright", SimpleNamespace(sync_api=sync_api))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)


def test_browser_fetch_success(monkeypatch, cache_dir):
    snapshot = "<html><body><div id='HEADER'></div><div id='CONTENT'>" + "word " * 200 + "</div></body></html>"
    _install_fake_playwright(monkeypatch, snapshot)
    body = F.fetch_snapshot("Pxjvq", cache_dir, use_browser=True)
    assert body == snapshot


def test_browser_fetch_still_challenge_raises(monkeypatch, cache_dir):
    import itertools

    challenge = '<html><div id="g-recaptcha"></div></html>'
    _install_fake_playwright(monkeypatch, challenge)

    counter = itertools.count()

    class FakeTime:
        @staticmethod
        def monotonic():
            return next(counter)

        @staticmethod
        def sleep(_seconds):
            return None

    monkeypatch.setattr("archive_kindle_cli.fetch.time", FakeTime)
    with pytest.raises(F.CaptchaBlocked):
        F.fetch_snapshot("Pxjvq", cache_dir, use_browser=True)


def test_browser_fetch_non_snapshot_raises(monkeypatch, cache_dir):
    import itertools

    # challenge cleared but page is not an archive snapshot -> still blocked
    _install_fake_playwright(monkeypatch, "<html><body>not a snapshot</body></html>")
    counter = itertools.count()

    class FakeTime:
        @staticmethod
        def monotonic():
            return next(counter)

        @staticmethod
        def sleep(_seconds):
            return None

    monkeypatch.setattr("archive_kindle_cli.fetch.time", FakeTime)
    with pytest.raises(F.CaptchaBlocked):
        F.fetch_snapshot("Pxjvq", cache_dir, use_browser=True)


def test_browser_fetch_missing_playwright(monkeypatch, cache_dir):
    monkeypatch.delitem(sys.modules, "playwright", raising=False)
    monkeypatch.delitem(sys.modules, "playwright.sync_api", raising=False)
    orig_import = __import__

    def no_playwright(name, *args, **kwargs):
        if name == "playwright.sync_api":
            raise ImportError("no playwright")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", no_playwright)
    with pytest.raises(F.FetchError, match="playwright"):
        F.fetch_snapshot("Pxjvq", cache_dir, use_browser=True)
