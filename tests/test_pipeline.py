from __future__ import annotations

import re
import zipfile

from lxml import etree

from archive_kindle_cli.pipeline import NoContentError, convert_html


def test_convert_real_snapshot_end_to_end(
    tmp_path, snapshot_html, snapshot_dir, cache_dir
):
    out = convert_html(
        snapshot_html,
        source_url="https://caravanmagazine.in/politics/manmohan-singh-cannot-ignore-congress",
        out_path=tmp_path / "out.epub",
        cache_dir=cache_dir,
        local_base=snapshot_dir,
    )
    assert out.exists() and out.stat().st_size > 10_000

    z = zipfile.ZipFile(out)
    ch = z.read("EPUB/chapter.xhtml").decode()
    body = re.search(r"<body>(.*)</body>", ch, re.S).group(1)
    words = len(re.sub(r"<[^>]+>", " ", body).split())
    assert words > 2000  # full article, not the paywalled teaser
    assert "Manmohan" in body

    for name in z.namelist():
        if name.endswith((".xml", ".xhtml", ".opf", ".ncx")):
            etree.fromstring(z.read(name))  # must parse

    refs = set(re.findall(r'src="(images/[^"]+)"', ch))
    missing = [r for r in refs if f"EPUB/{r}" not in z.namelist()]
    assert missing == []

    opf = z.read("EPUB/content.opf").decode()
    assert "caravanmagazine.in" in opf  # dc:source = original URL


def test_convert_default_output_name(tmp_path, cache_dir, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = convert_html(
        "<html><head><title>My Great Piece</title></head><body>"
        "<article><h1>My Great Piece</h1>" + ("<p>words words</p>" * 30)
        + "</article></body></html>",
        cache_dir=cache_dir,
        no_images=True,
    )
    assert out.name == "my-great-piece.epub"


def test_no_content_raises(tmp_path, cache_dir):
    import pytest

    with pytest.raises(NoContentError):
        convert_html("<html><head><title>Empty</title></head><body></body></html>",
                     cache_dir=cache_dir)
