"""Download article images, dedupe by content, and normalize to Kindle-friendly
formats (JPEG/PNG) with Pillow.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

import requests
from PIL import Image

from .fetch import UA

MAX_IMAGE_PIXELS = 50_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

_HEADERS = {
    "User-Agent": UA,
    "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class ImageAsset:
    filename: str  # e.g. images/img_0003.jpg
    mime: str
    data: bytes
    width: int
    height: int


class ImageFetchError(Exception):
    pass


def _normalize(data: bytes) -> tuple[bytes, str]:
    """Return (bytes, mime) guaranteed JPEG or PNG."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise ImageFetchError(f"not a decodable image: {exc}") from exc
    if img.format in ("JPEG", "PNG") and img.mode in ("RGB", "L", "P"):
        return data, "image/jpeg" if img.format == "JPEG" else "image/png"
    rgb = img.convert("RGB")
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        rgb = bg
    buf = io.BytesIO()
    rgb.save(buf, "JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"


def download_images(
    refs: list,
    *,
    cache_dir: Path,
    referer: str | None = None,
    no_images: bool = False,
    max_images: int = 150,
    local_base: Path | None = None,
    verbose: bool = False,
) -> tuple[dict[str, ImageAsset], ImageAsset | None]:
    """Download ImageRefs -> {placeholder: ImageAsset}; return best cover too.

    Failed downloads are skipped (missing from the mapping); the EPUB builder
    drops the corresponding <img> tags. ``refs`` items are extract.ImageRef.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    if no_images:
        return {}, None

    session = requests.Session()
    session.headers.update(_HEADERS)
    if referer:
        session.headers["Referer"] = referer

    assets: dict[str, ImageAsset] = {}
    seen: dict[str, str] = {}  # sha1 -> filename
    cover: ImageAsset | None = None

    for i, ref in enumerate(refs[:max_images]):
        if verbose:
            print(f"  image {i + 1}/{min(len(refs), max_images)}: {ref.src}", file=__import__("sys").stderr)
        src = ref.src
        if src.startswith("http://") or src.startswith("https://"):
            try:
                resp = session.get(src, timeout=30)
                resp.raise_for_status()
                raw = resp.content
            except requests.RequestException as exc:
                if verbose:
                    print(f"  skip {src}: {exc}", file=__import__("sys").stderr)
                continue
        elif local_base is not None:
            # Browser-saved pages rewrite image srcs to local paths.
            path = Path(src)
            if not path.is_absolute():
                path = local_base / path
            path = path.resolve()
            if not path.is_file():
                continue
            try:
                raw = path.read_bytes()
            except OSError:
                continue
        else:
            continue
        if not raw:
            continue
        try:
            data, mime = _normalize(raw)
        except ImageFetchError:
            continue
        with Image.open(io.BytesIO(data)) as im:
            width, height = im.size
        # Skip logos/icons/decoration: too small to matter in a book.
        if width < 200 or height < 150:
            continue
        digest = hashlib.sha1(data).hexdigest()
        filename = seen.get(digest)
        if filename is None:
            ext = "png" if mime == "image/png" else "jpg"
            filename = f"images/img_{len(seen):04d}.{ext}"
            seen[digest] = filename
        asset = ImageAsset(filename=filename, mime=mime, data=data, width=width, height=height)
        assets[ref.placeholder] = asset
        if cover is None:
            cover = asset
        elif width >= 800 and 1.0 <= height / width <= 2.0:
            cover = asset

    if len(refs) > max_images and verbose:
        print(f"  capped at {max_images} images", file=__import__("sys").stderr)
    return assets, cover
