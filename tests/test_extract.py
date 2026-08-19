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


def test_nested_article_beats_wrapper_root():
    # archive.today's #CONTENT wraps the whole saved page; when the page's
    # own <article> carries most of the text it must become the root, so
    # post-article chrome (recommended reading, author box) drops out.
    html = (
        "<!DOCTYPE html><html><head><title>Wrapper</title></head><body>"
        '<div id="HEADER"><a href="https://archive.today/">archive.today webpage capture</a></div>'
        '<div id="CONTENT">'
        "<article><h1>Real Article</h1>"
        "<p>" + "Article body sentence with several words. " * 60 + "</p>"
        "<h2>Subheading</h2><p>More body text after the subheading.</p>"
        "</article>"
        '<section class="more-articles">'
        "<h2>From the Wire</h2>"
        '<h3><a href="/other">Some Other Article</a></h3>'
        "<p>A blurb about the other article that is not part of this one.</p>"
        "</section>"
        "</div></body></html>"
    )
    art = extract_article(html)
    assert "Real Article" in art.body
    assert "Subheading" in art.body
    assert "From the Wire" not in art.body
    assert "Some Other Article" not in art.body


def test_chrome_widgets_nested_in_article_removed():
    # The Atlantic nests "Recommended Reading" and "About the Author" inside
    # its <article>. Those are furniture: their block is dropped even though
    # it is inside the picked content root.
    html = (
        "<!DOCTYPE html><html><head><title>Wrapper</title></head><body>"
        '<div id="HEADER"><a href="https://archive.today/">archive.today webpage capture</a></div>'
        '<div id="CONTENT"><article><h1>Real Article</h1>'
        "<p>" + "Article body sentence with several words. " * 40 + "</p>"
        '<div><h2>Recommended Reading</h2>'
        '<h3><a href="/other">Some Other Article</a></h3>'
        "<p>A blurb about the other article.</p></div>"
        "<p>" + "Final body paragraph that must survive. " * 20 + "</p>"
        '<div><h3>About the Author</h3><p>Author bio text goes here.</p></div>'
        "</article></div></body></html>"
    )
    art = extract_article(html)
    assert "Real Article" in art.body
    assert "Final body paragraph" in art.body
    assert "Recommended Reading" not in art.body
    assert "Some Other Article" not in art.body
    assert "About the Author" not in art.body
    assert "Author bio text" not in art.body


def test_large_section_with_chrome_heading_kept():
    # A large section that merely starts with a chrome label is article
    # content, not a widget: the size cap keeps it.
    html = (
        "<!DOCTYPE html><html><body>"
        "<article><h1>Story</h1>"
        '<section><h2>Recommended Reading</h2>'
        "<p>" + "Substantive section body that is clearly real content. " * 60 + "</p>"
        "</section></article></body></html>"
    )
    art = extract_article(html)
    assert "Substantive section body" in art.body


def test_chrome_heading_requires_exact_match():
    # A title merely containing a chrome word ("Trending: X") is article
    # content: the label match is exact, not a substring search.
    html = (
        "<!DOCTYPE html><html><body><article><h1>Story</h1>"
        "<p>" + "Intro body text word. " * 40 + "</p>"
        '<div><h2>Trending: A Short History</h2>'
        "<p>" + "Section body text word. " * 30 + "</p></div>"
        "</article></body></html>"
    )
    art = extract_article(html)
    assert "Trending: A Short History" in art.body


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


def test_archive_snapshot_strips_progress_widget_and_comments():
    # archive.today's scroll-progress widget: invalid XML ids ("0%") wrapped
    # in conditional comments — breaks Kindle's converter (E999).
    html = (
        '<html><body><a href="https://archive.ph/x">archive.today</a>'
        '<div id="CONTENT"><article><h1>T</h1><p>' + "words " * 100 + "</p>"
        "<!--[if !IE]><!--><table border=\"0\" id=\"hashtags\"><tbody>"
        '<tr><td id="0%"><a href="https://archive.ph/x#0%">0%</a></td></tr>'
        '<tr><td id="100%"><a href="https://archive.ph/x#100%">100%</a></td></tr>'
        "</tbody></table><!--<![endif]-->"
        "</article></div></body></html>"
    )
    art = extract_article(html)
    assert "hashtags" not in art.body
    assert "0%" not in art.body
    assert "<table" not in art.body
    assert "<!--" not in art.body
    assert "if !IE" not in art.body


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
