"""Fetching snapshots from archive.today mirrors.

archive.today aggressively rate-limits and serves an anti-bot challenge
(reCAPTCHA) to flagged IPs. This module keeps a persistent cookie jar,
primes the session on the homepage, paces retries, detects the challenge,
and optionally falls back to a headless browser.
"""

from __future__ import annotations

import re
import time
from http.cookiejar import MozillaCookieJar
from pathlib import Path

import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

#: Known archive.today mirror domains; every mirror serves every snapshot.
MIRRORS = {
    "archive.today",
    "archive.is",
    "archive.ph",
    "archive.li",
    "archive.md",
    "archive.vn",
    "archive.fo",
    "archive.yt",
    "archive.wf",
}

_ID_RE = re.compile(
    r"^(?:https?://(?:www\.)?(?:%s)/)?([A-Za-z0-9_-]+)(?:[?#].*)?$"
    % "|".join(sorted(MIRRORS)),
    re.IGNORECASE,
)

#: Body markers that indicate the anti-bot challenge instead of content.
_CHALLENGE_MARKERS = (
    "g-recaptcha",
    "chk_captcha",
    "one more step",
    "security check",
)

_HEADERS = {
    "User-Agent": UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class FetchError(Exception):
    """Base class for snapshot fetch failures."""


class CaptchaBlocked(FetchError):
    """archive.today served its anti-bot challenge (rate limited / flagged IP)."""


def normalize_url(value: str) -> str:
    """Accept a mirror URL or a bare snapshot id; return canonical archive.ph URL."""
    m = _ID_RE.match(value.strip())
    if not m:
        raise FetchError(
            f"not an archive.today snapshot URL or id: {value!r} "
            f"(expected e.g. https://archive.ph/Pxjvq or Pxjvq)"
        )
    return f"https://archive.ph/{m.group(1)}"


def _is_challenge(status: int, body: str) -> bool:
    if status in (403, 429):
        return True
    low = body[:200_000].lower()
    return any(marker in low for marker in _CHALLENGE_MARKERS)


def _save_jar(session: requests.Session, cache_dir: Path) -> None:
    jar = session.cookies
    if isinstance(jar, MozillaCookieJar):
        try:
            jar.save(ignore_discard=True, ignore_expires=True)
        except OSError:
            pass


def _new_session(cache_dir: Path) -> requests.Session:
    jar = MozillaCookieJar(str(cache_dir / "cookies.txt"))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (FileNotFoundError, requests.cookies.CookieConflictError):
        pass
    session = requests.Session()
    session.headers.update(_HEADERS)
    session.cookies = jar
    return session


def _fetch_browser(target: str, timeout: float) -> str:
    """Fetch through headless Chromium; passes challenges that need JS."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise FetchError(
            "playwright is not installed; run `uv pip install 'archive-kindle-cli[browser]'`"
        ) from exc
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=UA, viewport={"width": 1366, "height": 900}, locale="en-US"
        )
        page = ctx.new_page()
        page.goto(target, wait_until="domcontentloaded", timeout=timeout * 1000)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            html = page.content()
            if not _is_challenge(200, html):
                return html
            time.sleep(1)
        raise CaptchaBlocked(
            f"archive.today still served its anti-bot challenge in the browser for "
            f"{target}. Open the URL in your own browser and complete the captcha once."
        )


def fetch_snapshot(
    url: str,
    cache_dir: Path,
    *,
    use_browser: bool = False,
    timeout: float = 60.0,
) -> str:
    """Return the snapshot page HTML for an archive.today URL or id."""
    target = normalize_url(url)
    cache_dir.mkdir(parents=True, exist_ok=True)

    if use_browser:
        return _fetch_browser(target, timeout)

    session = _new_session(cache_dir)
    # Prime the session on the homepage; it sets the site cookie that keeps
    # subsequent snapshot requests out of the challenge.
    try:
        session.get("https://archive.ph/", timeout=timeout)
    except requests.RequestException as exc:
        raise FetchError(f"could not reach archive.today: {exc}") from exc
    _save_jar(session, cache_dir)

    body: str | None = None
    for attempt in (0, 1):
        if attempt:
            time.sleep(20)  # gentle backoff between attempts
        try:
            resp = session.get(
                target, timeout=timeout, headers={"Referer": "https://archive.ph/"}
            )
        except requests.RequestException as exc:
            if attempt == 1:
                raise FetchError(f"request failed: {exc}") from exc
            continue
        _save_jar(session, cache_dir)
        body = resp.text
        if not _is_challenge(resp.status_code, body):
            return body

    raise CaptchaBlocked(
        f"archive.today served its anti-bot challenge for {target}. "
        f"Wait a few minutes and retry, use --browser, or fetch once in a "
        f"regular browser to clear the block."
    )
