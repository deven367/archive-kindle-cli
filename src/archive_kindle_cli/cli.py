"""archive-kindle: convert an archive.today snapshot into a Kindle EPUB."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from . import __version__
from .fetch import CaptchaBlocked, FetchError, fetch_snapshot
from .pipeline import NoContentError, convert_html

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
) -> None:
    """Convert URL to EPUB."""
    try:
        if file is not None:
            eprint(f"reading {file}")
            html = file.read_text(encoding="utf-8", errors="replace")
            source_url = url if url.startswith("http") else None
        else:
            eprint(f"fetching {url}")
            html = fetch_snapshot(
                url, cache_dir, use_browser=browser, timeout=60.0
            )
            source_url = None

        eprint("extracting content")
        out_path = convert_html(
            html,
            source_url=source_url,
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


@app.command()
def version() -> None:
    """Print the version."""
    print(__version__)


if __name__ == "__main__":
    app()
