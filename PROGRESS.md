# Progress notes

Handoff notes for any agent (or future me) continuing this project.

## Goal

CLI that takes an archive.today (archive.is) snapshot URL and produces a
Kindle-readable EPUB with images. (Browser extension was prototyped and
dropped on user decision 2026-08-14 — CLI only.)

Working example: `archive.is/Pxjvq` → Caravan article "What we cannot ignore
about Manmohan Singh" (paywalled on the live site; the snapshot has the full
text).

## Status (2026-08-14)

- [x] Fetch layer: cookie-primed session, homepage priming, challenge
      detection (429/reCAPTCHA), 2-attempt backoff, `--browser` playwright
      fallback, persistent cookie jar in `~/.cache/archive-kindle/`.
- [x] Extraction: archive.today toolbar removal (`#HEADER`), junk removal
      (nav/ads/paywall boxes by class + text heuristics), content-root pick
      (`#CONTENT` for archive snapshots), image inventory with `<picture>`
      srcset support, placeholder srcs (`images/0000`).
- [x] Images: download w/ dedupe by sha1, Pillow normalization
      (WebP/GIF/PNG → JPEG), logo/tiny-image filter (<200w or <150h dropped),
      local-file fallback for browser-saved pages (`--file`).
- [x] EPUB: ebooklib EPUB3 + NCX, generated or image cover, TOC from h2/h3,
      Kindle-friendly CSS, dc:source = original URL.
- [x] CLI: `archive-kindle convert <url|id> [-o out.epub] [--file x.html]
      [--no-images] [--browser] [--title T] [--verbose]`.
- [x] Verified end-to-end against the REAL snapshot (`--file Pxjvq.html`):
      2491 words, 1 real image (800x560), valid XML throughout, no missing
      refs, correct title/author/source metadata.
- [x] Fetch layer verified against a local mock archive.ph server: happy
      path (priming + snapshot + cookie jar persisted), retry-after-429,
      captcha body → CaptchaBlocked, invalid input rejection.
- [ ] Live fetch of Pxjvq still UNVERIFIED (this IP remained 429-flagged the
      whole session, ~1.5h+). Retry from a clean IP; file-mode + mock-server
      tests cover the logic, only the real 200 path is unexercised.

## Verified facts about archive.today (important)

- Aggressive per-IP throttle: ~2-3 requests within a minute → 429 +
  reCAPTCHA for 10-60+ min. This IP was flagged for the whole session.
- Mirror domains (archive.ph/is/today/li/md/vn/fo/yt/wf) SHARE the block.
- Snapshot *image* endpoints (`archive.ph/<id>/<hash>.<ext>`) are NOT
  throttled — HTTP 200 even while pages 429. Tested: byte-identical WebP.
- Snapshot DOM: toolbar in `#HEADER`, content in `#CONTENT` (uppercase ids!),
  original URL in toolbar `input[name="q"]` (the "Saved from" box), snapshot
  timestamp in hidden field `t` (epoch ms). `<title>` = original page title
  (no archive suffix in this capture). Wordmark link text `archive.today`.
- Browser-saved pages rewrite image srcs to `./<page>_files/<hash>.<ext>`
  (local paths) — handled by `--file` + local-base image resolution.
- Caravan-specific quirks seen in Pxjvq: broken nesting (`<img>` inside
  `<source>` inside `<picture>`), hero image nested inside the site-nav
  `<header>`, paywall boxes mid-article ("We're glad this article found its
  way to you..." / "Thanks for reading till the end..."), JSON-LD present but
  unparseable in the snapshot.

## How to test

```bash
uv pip install -e .
# real snapshot file (in repo, browser-saved "complete" page)
.venv/bin/archive-kindle convert --file Pxjvq.html -o /tmp/pxjvq.epub \
  "https://caravanmagazine.in/politics/manmohan-singh-cannot-ignore-congress" --verbose
# live fetch — EXPECT exit 2 w/ captcha message while this IP is throttled
.venv/bin/archive-kindle convert "https://archive.is/Pxjvq" -o /tmp/pxjvq2.epub
# smoke test on any html:
.venv/bin/archive-kindle convert --file /tmp/live.html --no-images -o /tmp/t.epub URL
```

Validate: unzip -l; lxml-parse every .opf/.ncx/.xhtml; check chapter img refs
exist in package (epub_builder now adds EpubImage items — earlier bug: refs
without files).

## Tests & CI (2026-08-14)

- pytest suite (50 tests) with `--cov-fail-under=75`: 92.5% coverage.
  Hermetic: mock archive.today server, local image servers, committed
  Pxjvq.html fixture. `uv run pytest` runs it.
- GitHub Actions workflow `.github/workflows/ci.yml` (ubuntu, python 3.13,
  `uv sync --extra dev` + `uv run pytest`). uv.lock committed.
- Closes issue #3.

## Known issues / next steps

- [ ] Author extraction: JSON-LD author now captured before script removal
      (issue #1) — works when the JSON parses; Caravan's snapshot JSON-LD is
      malformed so it still falls back to "archive.today". Low priority.
- [ ] Cover: uses first ≥200x150 image (may be landscape; Kindle letterboxes).
      Fine for now.
- [ ] Verify live fetch works once the archive.today IP block clears (see
      issue #2).
- [ ] Consider `--keep-urls` / link handling in EPUB (links currently
      preserved but mostly dead in readers; acceptable).

## Environment

- uv venv, Python 3.13.9, deps: requests, beautifulsoup4, lxml, ebooklib,
  pillow, typer (+ optional playwright).
- CLI entry: `archive-kindle` (venv bin). Exit codes: 0 ok, 1 error, 2 captcha.
