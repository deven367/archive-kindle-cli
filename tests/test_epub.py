from __future__ import annotations

import io
import zipfile

from lxml import etree
from PIL import Image

from archive_kindle_cli.epub_builder import build_epub, _slugify, _xhtml
from archive_kindle_cli.extract import Article
from archive_kindle_cli.images import ImageAsset


def _jpeg_asset(filename="images/img_0000.jpg", size=(800, 560)) -> ImageAsset:
    buf = io.BytesIO()
    Image.new("RGB", size, (50, 100, 200)).save(buf, "JPEG")
    return ImageAsset(filename=filename, mime="image/jpeg", data=buf.getvalue(),
                      width=size[0], height=size[1])


def _article(title="A Test Article", body=None, source="https://example.com/a") -> Article:
    return Article(
        title=title,
        author="Jane Doe",
        language="en",
        source_url=source,
        body=body
        or "<h1>A Test Article</h1><p>Some <strong>body</strong> text here.</p>"
        '<h2 id="sec-0">Section</h2><p>More text.</p>'
        '<img src="images/0000" alt="pic"/>',
        images=[],
    )


def _parse_all(z: zipfile.ZipFile) -> list[str]:
    bad = []
    for name in z.namelist():
        if name.endswith((".xml", ".xhtml", ".opf", ".ncx")):
            try:
                etree.fromstring(z.read(name))
            except Exception as exc:  # noqa: BLE001
                bad.append(f"{name}: {exc}")
    return bad


def test_build_epub_basic(tmp_path):
    art = _article()
    assets = {"images/0000": _jpeg_asset()}
    out = build_epub(art, assets, _jpeg_asset(), tmp_path / "out.epub")
    assert out.exists()

    z = zipfile.ZipFile(out)
    names = z.namelist()
    assert names[0] == "mimetype"
    assert "META-INF/container.xml" in names
    assert "EPUB/content.opf" in names
    assert "EPUB/chapter.xhtml" in names
    assert "EPUB/toc.ncx" in names
    assert "EPUB/nav.xhtml" in names
    assert "EPUB/images/img_0000.jpg" in names
    assert _parse_all(z) == []

    ch = z.read("EPUB/chapter.xhtml").decode()
    assert 'src="images/img_0000.jpg"' in ch
    assert '<h2 id="sec-0"' in ch

    ncx = z.read("EPUB/toc.ncx").decode()
    assert ncx.count("<navPoint") == 2  # chapter + section

    opf = z.read("EPUB/content.opf").decode()
    assert "<dc:title>A Test Article</dc:title>" in opf
    assert "<dc:creator" in opf and "Jane Doe" in opf
    assert "<dc:language>en</dc:language>" in opf
    assert "<dc:source>https://example.com/a</dc:source>" in opf


def test_missing_asset_drops_img_tag(tmp_path):
    art = _article()  # body references images/0000, but no asset provided
    out = build_epub(art, {}, None, tmp_path / "out.epub")
    z = zipfile.ZipFile(out)
    ch = z.read("EPUB/chapter.xhtml").decode()
    assert "images/0000" not in ch  # placeholder removed, not left dangling
    assert _parse_all(z) == []


def test_generated_text_cover_when_no_image(tmp_path):
    art = _article()
    out = build_epub(art, {}, None, tmp_path / "out.epub")
    z = zipfile.ZipFile(out)
    cover = z.read("EPUB/images/cover.jpg")
    with Image.open(io.BytesIO(cover)) as im:
        assert im.format == "JPEG"
    assert "EPUB/cover.xhtml" in z.namelist()


def test_non_ascii_title(tmp_path):
    art = _article(title="Naïve résumé — 日本語")
    out = build_epub(art, {}, None, tmp_path / "out.epub")
    z = zipfile.ZipFile(out)
    assert _parse_all(z) == []
    opf = z.read("EPUB/content.opf").decode()
    assert "Naïve résumé" in opf


def test_dedupe_image_items_by_filename(tmp_path):
    art = _article()
    same = _jpeg_asset()
    # two placeholders mapping to the same physical filename
    assets = {"images/0000": same, "images/0001": same}
    out = build_epub(art, assets, None, tmp_path / "out.epub")
    z = zipfile.ZipFile(out)
    count = [n for n in z.namelist() if n == "EPUB/images/img_0000.jpg"]
    assert len(count) == 1


def test_slugify():
    assert _slugify("Hello, World!") == "hello-world"
    assert _slugify("日本語") == "article"  # fallback for non-ascii
    assert _slugify("") == "article"


def test_xhtml_is_well_formed():
    content = _xhtml("<p>Hello <strong>world</strong></p><img src='images/0000'/>", "T", "en")
    etree.fromstring(content.encode())  # must not raise
    assert "<?xml" not in content  # prolog omitted on purpose
