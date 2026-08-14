# archive-kindle-cli

CLI that converts [archive.today](https://archive.ph/) (archive.is) snapshots
into Kindle-ready EPUBs with images.

Works around archive.today's aggressive anti-bot throttling: persistent
session cookies, gentle pacing, challenge detection, and an optional
interactive Chromium fallback.

## Install

```bash
uv pip install -e .
# optional: headless-browser fetching (playwright + chromium)
uv pip install '.[browser]'
uv run playwright install chromium
```

## Usage

```bash
archive-kindle convert https://archive.is/Pxjvq
archive-kindle convert Pxjvq -o manmohan.epub
archive-kindle convert https://archive.ph/AbCdE --browser --verbose
```

With `--browser` a **visible** Chromium window opens (persistent profile). If
archive.today shows its CAPTCHA, solve it in that window — the CLI waits (3
min default) and continues automatically once the snapshot loads. The solved
cookies are saved to the session cache, so later runs (including plain
non-`--browser` fetches) reuse the clearance.

Options:

| Flag | Meaning |
| --- | --- |
| `-o, --output PATH` | output `.epub` (default `<title>.epub`) |
| `--title T` | override the document title |
| `--no-images` | skip image download |
| `--browser` | open a visible Chromium to solve the CAPTCHA interactively (needs `[browser]` extra) |
| `--file PATH` | build from a local HTML file instead of fetching (dev/testing aid; supports browser-saved pages) |
| `--cache-dir PATH` | session cookie cache (default `~/.cache/archive-kindle`) |
| `--max-images N` | cap downloads (default 150) |
| `--verbose` | per-image progress on stderr |

Output EPUBs are EPUB 3 with NCX (legacy-device TOC), a cover, embedded
images (normalized to JPEG/PNG), and a document-local stylesheet. Kindle
(2022+) reads EPUB natively; Send to Kindle converts to KFX/AZW3.

Exit codes: `0` success, `1` error, `2` archive.today anti-bot block
(retry later, use `--browser`, or clear the captcha in a browser once).

## Tests

```bash
uv pip install -e '.[dev]'
uv run pytest          # requires >75% coverage (currently ~93%)
```

Hermetic — no real network: fetch tests use a local mock archive.today
server, image tests use local HTTP servers and files, and the extraction
pipeline is exercised against the committed `Pxjvq.html` snapshot fixture.
CI runs the same suite on GitHub Actions (`.github/workflows/ci.yml`).

## How it works

1. **fetch** — cookie-primed session on `archive.ph`, snapshot request with
   referer, 2-attempt backoff; detects the reCAPTCHA challenge and reports it
   clearly; `--browser` opens a visible Chromium for interactive solving.
2. **extract** — strips the archive.today toolbar (`#HEADER`), removes ads /
   nav / paywall boxes, picks the content root (`#CONTENT`), keeps headings /
   paragraphs / lists / tables / quotes / code / images, handles
   `<picture><source srcset>` and hoists images out of chrome `<header>`s.
3. **images** — downloads with content dedupe, converts WebP/GIF/PNG to
   Kindle-friendly JPEG/PNG, drops logos/tiny images.
4. **epub** — ebooklib EPUB3: cover, chapter, TOC from h2/h3, NCX + nav.

See `PROGRESS.md` for verified archive.today behavior and current status.
