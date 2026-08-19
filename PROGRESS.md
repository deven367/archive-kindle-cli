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
- The Atlantic snapshot "The Ordinary Miracle of Existing" verified
  end-to-end (1.3 MB EPUB, in-article "Recommended Reading" /
  "About the Author" widgets stripped, TOC labels are heading text).
- 82 hermetic tests, 93% coverage, GitHub Actions CI green.
- All issues closed except #6 (arbitrary live URLs via modular fetch
  backends), the open long-term item. `--send` (#8) is merged on main.

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

## Site handling — one generic path, no per-site classes

The Atlantic and The Caravan are both handled by the single extractor in
`extract.py`; the code contains **no site-specific branches** (the site
names appear only in comments). Each site's quirks were generalized into
shared heuristics instead:

- **In-article chrome widgets** (The Atlantic nests "Recommended Reading"
  and "About the Author" blocks *inside* `<article>`): any small
  div/section (≤1500 chars, `_WIDGET_MAX_CHARS`) whose first heading
  matches a known widget label (`_CHROME_HEADINGS`, plus "More from|on|by
  …" prefixes) is dropped in `_remove_junk`.
- **Wrapper-yielding content root** (`_pick_content_root`): when content
  candidates nest, a wrapper that merely contains a candidate carrying
  ≥50% of its text yields to the inner one, so post-article chrome drops
  out (archive.today's `#CONTENT` around the page's own `<article>`,
  `<main>` around `<article>`).
- **Caravan DOM damage**: broken `<img>`-in-`<source>` nesting resolved by
  walking up to `<picture>`; hero images hoisted out of site `<header>`
  before junk removal; author from byline links to `/author/<slug>`.
- **TOC labels** (`epub_builder._toc_from_body`): the heading's text with
  tags stripped and entities decoded — not the anchor id.

**Decision (2026-08-19): no `BaseExtractor`/`AtlanticExtractor`/
`CaravanExtractor` inheritance hierarchy.** There is no per-site behavior
to override yet — subclasses would be config-dispatch with empty bodies —
and the tool targets *arbitrary* archived sites, where a per-site class
zoo does not scale. Escalation path when a future site genuinely
diverges (different root strategy, image, or author semantics): add a
data-driven `SiteProfile` (domain → extra content selectors / junk
patterns + optional hook callables) in a registry, and give a site a
profile only when the generic path demonstrably fails for it.

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
- **Snapshots inject a scroll-progress widget**: a `#hashtags` table of
  `id="0%"`..`id="100%"` jump cells wrapped in `<!--[if !IE]><!-->`
  conditional comments. Amazon's converter rejects the resulting XHTML with
  **E999 - Send to Kindle Internal Error** (verified: Gmail delivered, Amazon
  bounced). Extractor strips the widget, all comments, and drops failed-image
  `<img>` tags wholesale (a src-less `<img>` also trips the converter).
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
