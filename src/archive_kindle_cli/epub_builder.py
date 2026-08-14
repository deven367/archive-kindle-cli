"""Build a Kindle-compatible EPUB from an extracted Article.

EPUB 3 with NCX for legacy devices, generated or image cover, and a
document-local stylesheet. Kindle (2022+) reads EPUB natively; Send to
Kindle converts this to KFX/AZW3 without changes.
"""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

from ebooklib import epub
from PIL import Image, ImageDraw, ImageFont

from .extract import Article
from .images import ImageAsset

CSS = """\
body { font-family: serif; line-height: 1.5; }
h1 { font-size: 1.5em; margin: 1em 0 0.5em; text-align: left; }
h2 { font-size: 1.25em; margin: 1.2em 0 0.4em; page-break-after: avoid; }
h3 { font-size: 1.1em; margin: 1em 0 0.3em; }
p { margin: 0 0 0.8em; text-align: justify; }
img { max-width: 100%; height: auto; }
figure { margin: 1em 0; text-align: center; }
figcaption { font-size: 0.85em; font-style: italic; text-align: center; }
blockquote { font-style: italic; margin: 1em 1.5em; }
pre { white-space: pre-wrap; font-size: 0.85em; margin: 1em 0; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; }
th, td { border: 1px solid #999; padding: 0.3em 0.5em; text-align: left; }
ul, ol { margin: 0 0 0.8em 1.5em; }
hr { margin: 1.5em 0; }
"""

#: void elements are serialized HTML-style by bs4; close them for XHTML.
_VOID_RE = re.compile(r"<(img|br|hr|meta|link|input|source|area|base|col|embed|track|wbr)([^>]*?)(?<!/)>")
_SRC_RE = re.compile(r'src="(images/\d{4})"')


def _slugify(text: str, fallback: str = "article") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:80] or fallback


def _fonts() -> list[str]:
    candidates = [
        "/System/Library/Fonts/Supplemental/Georgia.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    ]
    return [c for c in candidates if Path(c).exists()]


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    for para in text.splitlines() or [text]:
        words = para.split()
        current = ""
        for word in words:
            trial = f"{current} {word}".strip()
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines


def _text_cover(title: str, source: str | None) -> ImageAsset:
    """Generated 3:4 cover with the article title; no external deps beyond Pillow."""
    width, height = 1200, 1600
    img = Image.new("RGB", (width, height), (250, 247, 240))
    draw = ImageDraw.Draw(img)
    fonts = _fonts()
    title_font = ImageFont.truetype(fonts[0], 64) if fonts else ImageFont.load_default()
    small_font = ImageFont.truetype(fonts[0], 28) if fonts else ImageFont.load_default()

    margin = 100
    lines = _wrap_text(draw, title, title_font, width - 2 * margin)[:12]
    y = height * 0.35
    for line in lines:
        draw.text((margin, y), line, fill=(40, 40, 40), font=title_font)
        y += 80
    footer = source or ""
    if footer:
        footer = footer[:60]
        for line in _wrap_text(draw, footer, small_font, width - 2 * margin)[:2]:
            draw.text((margin, height - 200), line, fill=(120, 120, 120), font=small_font)
            y += 0
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return ImageAsset(filename="cover.jpg", mime="image/jpeg", data=buf.getvalue(),
                      width=width, height=height)


def _xhtml(body_fragment: str, title: str, lang: str) -> str:
    # No XML prolog: ebooklib/lxml refuse encoding declarations in str input,
    # and it is optional for EPUB3 XHTML documents.
    body_fragment = _VOID_RE.sub(r"<\1\2 />", body_fragment)
    return f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}" lang="{lang}">
<head>
<meta charset="utf-8"/>
<title>{title}</title>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
{body_fragment}
</body>
</html>"""


def _toc_from_body(body: str, title: str) -> tuple:
    anchors = re.findall(r'<h[23][^>]*id="([^"]+)"', body)
    if not anchors:
        return (epub.Link("chapter.xhtml", title, "chapter"),)
    toc = [epub.Link("chapter.xhtml", title, "chapter")]
    for anchor in anchors:
        toc.append(epub.Link(f"chapter.xhtml#{anchor}", f"Section: {anchor}", anchor))
    return tuple(toc)


def build_epub(
    article: Article,
    assets: dict,
    cover_asset,
    out_path: Path,
    *,
    title_override: str | None = None,
    source_label: str | None = None,
) -> Path:
    """Write the EPUB. ``assets`` maps placeholder -> ImageAsset; ``cover_asset``
    may be None (then a text cover is generated)."""
    title = (title_override or article.title or "Archived page").strip()
    lang = article.language or "en"

    book = epub.EpubBook()
    identifier = hashlib.sha1((article.source_url or title).encode()).hexdigest()[:16]
    book.set_identifier(identifier)
    book.set_title(title)
    book.set_language(lang)
    book.add_author(article.author or "archive.today")
    if article.source_url:
        book.add_metadata("DC", "source", article.source_url)

    # Cover
    if cover_asset is None:
        cover_asset = _text_cover(title, article.source_url or source_label)
    book.set_cover("images/cover.jpg", cover_asset.data, create_page=True)

    # Chapter
    body = article.body
    added_filenames: set[str] = set()
    for placeholder, asset in assets.items():
        body = body.replace(f'src="{placeholder}"', f'src="{asset.filename}"')
        if asset.filename not in added_filenames:
            book.add_item(
                epub.EpubImage(
                    uid=f"img-{asset.filename.replace('/', '-')}",
                    file_name=asset.filename,
                    media_type=asset.mime,
                    content=asset.data,
                )
            )
            added_filenames.add(asset.filename)
    body = _SRC_RE.sub("", body)  # drop images that failed to download
    chapter = epub.EpubHtml(uid="chapter", file_name="chapter.xhtml", title=title, lang=lang)
    chapter.content = _xhtml(body, title, lang)
    book.add_item(chapter)

    css = epub.EpubItem(uid="style", file_name="style.css", media_type="text/css", content=CSS)
    book.add_item(css)

    book.toc = _toc_from_body(body, title)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    book.spine = ["nav", chapter]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out_path), book)
    return out_path
