"""Shared HTML -> EPUB conversion pipeline used by both the CLI and the
local server backing the browser extension.
"""

from __future__ import annotations

from pathlib import Path

from .epub_builder import _slugify, build_epub
from .extract import extract_article
from .images import download_images


class NoContentError(ValueError):
    """The page yielded no readable content."""


def convert_html(
    html: str,
    *,
    source_url: str | None = None,
    out_path: Path | None = None,
    cache_dir: Path,
    title: str | None = None,
    no_images: bool = False,
    max_images: int = 150,
    local_base: Path | None = None,
    verbose: bool = False,
) -> Path:
    """Extract, download images, and write the EPUB. Returns the output path."""
    article = extract_article(html, source_url=source_url, base_url=source_url)
    if not article.body.strip():
        raise NoContentError("no readable content found in the page")
    if out_path is None:
        out_path = Path(f"{_slugify(title or article.title)}.epub")
    assets, cover = download_images(
        article.images,
        cache_dir=cache_dir / "images",
        referer=source_url,
        no_images=no_images,
        max_images=max_images,
        local_base=local_base,
        verbose=verbose,
    )
    build_epub(
        article,
        assets,
        cover,
        out_path,
        title_override=title,
    )
    return out_path
