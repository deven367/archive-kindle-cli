# Progress notes

Handoff notes for any agent (or future me) continuing this project.

## What this is

`archive-kindle` — a CLI that converts an archive.today (archive.is)
snapshot URL into a Kindle-readable EPUB with images.

Working example: `archive.is/Pxjvq` → Caravan article "What we cannot ignore
about Manmohan Singh" (paywalled on the live site; the snapshot carries the
full text). Live fetch + image download both verified end-to-end.

A browser extension was prototyped and dropped on user decision (CLI only).

## Current state — complete and verified

- Fetch, extract, image download, EPUB build, and CLI all work end-to-end
  against the live site (2491 words + embedded 800×560 image, correct
  title/author/source metadata).
- 65 hermetic tests, 93% coverage, GitHub Actions CI green.
- Issues #1–#5 closed; #7 (Send to Kindle via `--send`) implemented and
  pending merge. #6 (arbitrary live URLs via modular fetch backends) is the
  open long-term item.

## Architecture

| Module | Responsibility |
| --- | --- |
| `fetch.py` | archive.today session: cookie-primed requests, challenge detection (429/reCAPTCHA), retry/backoff, interactive `--browser` fallback, cookie persistence |
| `extract.py` | DOM → `Article`: toolbar removal, junk/paywall stripping, content-root selection, image inventory (placeholders + base_url resolution), title/author/source |
| `images.py` | download with sha1 dedupe, Pillow normalization (WebP/GIF/PNG→JPEG), logo filter, local-file fallback |
| `epub_builder.py` | ebooklib EPUB3 + NCX: cover (image or generated), chapter XHTML, TOC from h2/h3, Kindle CSS, `dc:source` |
| `pipeline.py` | `convert_html()` — shared orchestration for CLI (and any future frontend) |
| `send.py` | `--send`: emails the built EPUB to the Kindle address via stdlib SMTP (env-var config, 50 MB check, actionable errors) |
| `cli.py` | typer entrypoint: `convert` (the main command) and `version` |

## Verified archive.today behavior (important, non-obvious)

- **Aggressive per-IP throttle**: a burst of requests → 429 + reCAPTCHA for
  10-60+ min. Applies to **both** pages and images. Mirror domains
  (archive.ph/is/today/li/md/vn/fo/yt/wf) share the block.
- **Solving the CAPTCHA once** (in `--browser`, or a normal browser) yields a
  `cf_clearance` + `qki` cookie. Persisting those cookies clears the challenge
  for subsequent page *and* image requests from the CLI.
- **Snapshot DOM**: toolbar in `#HEADER`, article in `#CONTENT` (uppercase
  ids), original URL in the toolbar's `input[name="q"]` ("Saved from" box),
  snapshot timestamp in a hidden `t` field (epoch ms). `<title>` = original
  page title (no archive suffix).
- **Image `src`s are site-root-relative** (`/Pxjvq/<hash>.webp`) and must be
  resolved against `https://archive.ph/` before download.
- Browser-saved ("complete") pages rewrite image srcs to local
  `./<page>_files/<hash>.<ext>` paths — handled by `--file` + local-base.
- Caravan quirks seen in Pxjvq: broken nesting (`<img>` inside `<source>`
  inside `<picture>`), hero image nested inside the site-nav `<header>`,
  paywall boxes mid-article, empty JSON-LD, author only present as a byline
  link to `/author/<slug>`.

## `--browser` semantics

`--browser` opens a **headed** Chromium with a persistent profile
(`~/.cache/archive-kindle/browser-profile`). Solve the CAPTCHA in that window;
the CLI waits (3 min default) for `#CONTENT` to hold substantial text, then
copies the solved cookies into the requests jar so plain fetches work after.

## Testing & CI

```bash
uv pip install -e '.[dev]'   # or: uv sync --extra dev
uv run pytest                # >75% coverage required (currently ~92%)
```

Hermetic (no real network): mock archive.today server, local HTTP image
servers, and the committed `Pxjvq.html` fixture. GitHub Actions runs the same
suite on push/PR (`.github/workflows/ci.yml`, `uv.lock` committed).

## Known limitations / next steps

- Cover uses the first ≥200×150 image; may be landscape (Kindle letterboxes).
- Links are preserved but mostly dead inside readers — acceptable for now.
- No `--keep-urls`/link-rendering mode.

## Workflow

- Fix issues on a branch and open a PR (do not push directly to `main`).
- Reference `Fixes #N` in the commit/PR body to auto-close the issue.
- Keep `PROGRESS.md` current as a handoff point.

## Environment

- uv venv, Python 3.13.9. Deps: requests, beautifulsoup4, lxml, ebooklib,
  pillow, typer (+ optional playwright for `--browser`).
- CLI entry: `archive-kindle` (venv bin). Exit codes: 0 ok, 1 error, 2 captcha.
