"""archive-kindle: convert an archive.today snapshot into a Kindle EPUB."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from . import __version__
from .fetch import CaptchaBlocked, FetchError, fetch_snapshot, normalize_url
from .pipeline import NoContentError, convert_html
from .send import SendError, check_send_env, send_epub

app = typer.Typer(
    help="Convert archive.today snapshots into Kindle-ready EPUBs.",
    no_args_is_help=True,
)


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


@app.command()
def convert(
    url: Annotated[
        str,
        typer.Argument(help="archive.today snapshot URL or id (e.g. https://archive.ph/Pxjvq or Pxjvq)"),
    ],
    output: Annotated[
        Optional[Path],
        typer.Option("--output", "-o", help="output .epub path (default: <title>.epub)"),
    ] = None,
    title: Annotated[
        Optional[str],
        typer.Option("--title", help="override the document title"),
    ] = None,
    no_images: Annotated[
        bool,
        typer.Option("--no-images", help="skip image download"),
    ] = False,
    browser: Annotated[
        bool,
        typer.Option("--browser", help="fetch via headless Chromium (needs the [browser] extra)"),
    ] = False,
    file: Annotated[
        Optional[Path],
        typer.Option("--file", help="build from a local HTML file instead of fetching"),
    ] = None,
    cache_dir: Annotated[
        Path,
        typer.Option("--cache-dir", help="session cache directory"),
    ] = Path("~/.cache/archive-kindle").expanduser(),
    max_images: Annotated[
        int,
        typer.Option("--max-images", help="maximum images to download"),
    ] = 150,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="verbose progress output"),
    ] = False,
    send: Annotated[
        bool,
        typer.Option("--send", help="email the EPUB to your Kindle (needs AK_SMTP_USER, AK_SMTP_PASSWORD, AK_KINDLE_EMAIL env vars)"),
    ] = False,
) -> None:
    """Convert URL to EPUB."""
    if send:
        # Fail before doing any fetch/convert work: a missing env var is a
        # one-line fix, and the user shouldn't wait out a conversion to learn.
        try:
            check_send_env()
        except SendError as exc:
            eprint(f"error: {exc}")
            raise typer.Exit(1) from exc

    try:
        if file is not None:
            eprint(f"reading {file}")
            html = file.read_text(encoding="utf-8", errors="replace")
            source_url = url if url.startswith("http") else None
            base_url = source_url
        else:
            eprint(f"fetching {url}")
            html = fetch_snapshot(
                url, cache_dir, use_browser=browser, timeout=60.0
            )
            source_url = None
            base_url = normalize_url(url)

        eprint("extracting content")
        out_path = convert_html(
            html,
            source_url=source_url,
            base_url=base_url,
            out_path=output,
            cache_dir=cache_dir,
            title=title,
            no_images=no_images,
            max_images=max_images,
            local_base=file.parent if file is not None else None,
            verbose=verbose,
        )
        eprint("done")
    except CaptchaBlocked as exc:
        eprint(f"error: {exc}")
        raise typer.Exit(2) from exc
    except (FetchError, NoContentError, OSError) as exc:
        eprint(f"error: {exc}")
        raise typer.Exit(1) from exc

    print(out_path)

    if send:
        eprint("sending to Kindle")
        try:
            recipient = send_epub(out_path)
            eprint(f"emailed {out_path.name} to {recipient}")
            eprint(
                "conversion on Amazon's side is async (minutes); re-sends create "
                "duplicate documents in your library"
            )
            eprint(
                "if Amazon never delivers, approve the sender at amazon.com -> "
                "Content & Devices -> Preferences -> Personal Document Settings"
            )
        except SendError as exc:
            eprint(f"error: {exc}")
            eprint(f"EPUB still saved at {out_path}")
            raise typer.Exit(1) from exc


@app.command()
def version() -> None:
    """Print the version."""
    print(__version__)


if __name__ == "__main__":
    app()
