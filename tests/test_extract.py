from __future__ import annotations

from archive_kindle_cli.extract import extract_article


def test_plain_article(article_html):
    art = extract_article(article_html, source_url="https://example.com/politics/test-article")
    assert art.title == "Test Article | Example Site"
    assert art.author == "Jane Doe"  # from JSON-LD
    assert art.language == "en"
    assert art.source_url == "https://example.com/politics/test-article"
    assert "Body paragraph one" in art.body
    assert "A pull quote worth keeping" in art.body
    assert "<h2" in art.body
    assert '<h2 id="sec-0"' in art.body
    assert "Copyright example" not in art.body  # footer removed
    assert "Home" not in art.body  # nav removed
    assert "More articles" not in art.body  # aside removed
    assert "logo" not in art.body  # header chrome gone (logo outside root)
    assert "Sponsored" not in art.body  # ad class removed
    # two article images collected with placeholders
    assert [r.placeholder for r in art.images] == ["images/0000", "images/0001"]
    assert art.images[0].src == "https://cdn.example.com/photo1.webp"
    assert art.images[1].src == "https://cdn.example.com/photo2.jpg"
    assert 'src="images/0000"' in art.body
    assert 'src="images/0001"' in art.body


def test_archive_snapshot_strips_toolbar_and_finds_source(snapshot_page_html):
    art = extract_article(snapshot_page_html)
    assert art.source_url == "https://example.com/politics/original-piece"  # Saved from input
    assert art.title == "Archived Piece | Original Site"
    assert "archive.today" not in art.body
    assert "Buy me a coffee" not in art.body
    assert "Saved from" not in art.body
    assert "Sponsored content" not in art.body  # ad class
    assert "subscribe" not in art.body.lower()  # paywall box
    assert "The Good Piece" in art.body  # h1 kept
    assert len(art.images) == 2  # hero img + picture source img
    assert art.images[1].src == "https://archive.ph/Pxjvq/big1234.jpg"  # srcset resolved


def test_heading_ids_are_added_for_toc(snapshot_page_html):
    art = extract_article(snapshot_page_html)
    assert 'id="sec-0"' in art.body


def test_scheme_relative_images_normalized(article_html):
    art = extract_article(article_html)
    # the header logo is hoisted then dropped (outside root); assert no bare // srcs
    assert "//cdn.example.com" not in art.body


def test_data_uri_images_dropped():
    html = (
        "<html><body><main><article>"
        "<h1>T</h1><p>Enough content here to pass the threshold for selection.</p>"
        '<img src="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=" alt="icon"/>'
        '<img src="https://cdn.example.com/real.jpg" alt="real"/></article></main></body></html>'
    )
    art = extract_article(html)
    assert len(art.images) == 1
    assert art.images[0].src == "https://cdn.example.com/real.jpg"


def test_javascript_links_unwrapped(article_html):
    art = extract_article(article_html)
    assert "javascript:" not in art.body


def test_jsonld_article_body_fallback():
    html = (
        "<html><head><title>Thin page</title>"
        '<script type=\'application/ld+json\'>'
        '{"@type":"Article","articleBody":"Para one of the full text.\\n\\n'
        "Para two with plenty of words to exceed the minimum threshold for "
        "content extraction and to make sure the fallback path engages with "
        "enough substance that the extractor accepts it as real article "
        "content rather than a stub.\\n\\n"
        "Para three wraps up the piece nicely with more substance. The full "
        "text lives only in the JSON-LD because the visible DOM is just a "
        "paywall teaser, so the fallback must kick in and produce paragraphs "
        "from the embedded body instead of the thin page markup.\\n\\n"
        "Para four adds a little more padding to comfortably clear the "
        "minimum character threshold required by the extractor.\"}"
        "</script></head><body><main><article><h1>Thin</h1>"
        "<p>Only a teaser with a couple of words.</p></article></main></body></html>"
    )
    art = extract_article(html)
    assert art.title == "Thin page"
    assert art.body.count("<p>") >= 3
    assert "Para one of the full text" in art.body
    assert art.images == []


def test_empty_page_yields_empty_body():
    art = extract_article("<html><head><title>X</title></head><body></body></html>")
    assert art.body.strip() == ""


def test_archive_detection_without_toolbar_links():
    # wordmark link detection
    html = (
        '<html><body><a href="https://archive.ph/x">archive.today</a>'
        '<div id="CONTENT"><article><h1>T</h1><p>' + "words " * 100 + "</p></article></div>"
        "</body></html>"
    )
    art = extract_article(html)
    assert "archive.today" not in art.body


def test_relative_image_src_resolved_against_base_url():
    html = (
        '<html><body><main><article><h1>T</h1>'
        + "word " * 60
        + '<p>text</p><img src="/Pxjvq/abc123.webp" alt="x"/></article></main></body></html>'
    )
    art = extract_article(html, base_url="https://archive.ph/Pxjvq")
    assert art.images[0].src == "https://archive.ph/Pxjvq/abc123.webp"


def test_scheme_relative_image_normalized_without_base_url():
    html = (
        '<html><body><main><article><h1>T</h1>'
        + "word " * 60
        + '<p>text</p><img src="//cdn.example.com/a.webp" alt="x"/></article></main></body></html>'
    )
    art = extract_article(html)
    assert art.images[0].src == "https://cdn.example.com/a.webp"


def test_author_from_byline_link():
    html = (
        '<html><head><title>T</title></head><body><main><article><h1>T</h1>'
        + "word " * 60
        + '<p>text</p><a href="https://example.com/author/hartosh-singh-bal">Hartosh Singh Bal</a>'
        + '<p>more text</p></article></main></body></html>'
    )
    art = extract_article(html)
    assert art.author == "Hartosh Singh Bal"


def test_author_link_not_nav_link():
    # a nav link to an "authors" index page must not be treated as the byline
    html = (
        '<html><head><title>T</title></head><body><main><article><h1>T</h1>'
        + "word " * 60
        + '<p>text</p><a href="/authors">Authors</a><p>more text</p></article></main></body></html>'
    )
    art = extract_article(html)
    assert art.author is None
