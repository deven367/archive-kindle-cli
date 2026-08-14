from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SNAPSHOT_FIXTURE = REPO / "Pxjvq.html"


@pytest.fixture
def snapshot_html() -> str:
    """The real browser-saved archive.today snapshot (committed fixture)."""
    return (REPO / "Pxjvq.html").read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def snapshot_dir() -> Path:
    return REPO / "Pxjvq_files"


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "cache"


ARTICLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Test Article | Example Site</title>
  <link rel="canonical" href="https://example.com/politics/test-article"/>
  <script type="application/ld+json">{"@type":"Article","author":{"name":"Jane Doe"}}</script>
</head>
<body>
  <nav><a href="/">Home</a><a href="/politics">Politics</a></nav>
  <header class="site-header"><img src="//cdn.example.com/logo.png" alt="logo"/></header>
  <main>
    <article>
      <h1>Test Article</h1>
      <p class="standfirst">This is the standfirst with enough words to be meaningful content.</p>
      <p>Body paragraph one. Lorem ipsum dolor sit amet, consectetur adipiscing elit,
         sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad
         minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea
         commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit
         esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat
         non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.</p>
      <img src="https://cdn.example.com/photo1.webp" alt="A photo"/>
      <h2>Section One</h2>
      <p>Second section body text with plenty of words to count as real content.</p>
      <blockquote>A pull quote worth keeping.</blockquote>
      <ul><li>item one</li><li>item two</li></ul>
      <figure><img src="https://cdn.example.com/photo2.jpg" alt="Figure caption"/></figure>
    </article>
  </main>
  <aside class="related">More articles you might like <a href="/x">X</a></aside>
  <footer><p>Copyright example</p></footer>
</body>
</html>
"""


@pytest.fixture
def article_html() -> str:
    return ARTICLE_HTML


SNAPSHOT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Archived Piece | Original Site</title>
</head>
<body>
  <div id="HEADER">
    <a href="https://archive.today/">archive.today webpage capture</a>
    <div>Saved from</div>
    <input type="text" name="q" value="https://example.com/politics/original-piece"/>
    <a href="https://archive.is/original-site.com">All snapshots from host</a>
    <a href="https://liberapay.com/archiveis/donate">Buy me a coffee</a>
  </div>
  <div id="CONTENT">
    <h1>The Good Piece</h1>
    <p>The first paragraph of the archived article with a good number of words
       to keep the extractor happy and the content selection working well.</p>
    <img src="https://archive.ph/Pxjvq/abc123.webp" alt="hero image"/>
    <div class="ad-container"><p>Sponsored content</p></div>
    <div><p>We're glad this article found its way to you. If you're not a
       subscriber yet, subscribe now to keep reading.</p></div>
    <h2>Background</h2>
    <p>More body text here. Another paragraph of substance for the article.
       This is enough to pass the minimum content threshold comfortably.</p>
    <picture><source srcset="//archive.ph/Pxjvq/big1234.jpg 1200w"/><img alt="big photo"/></picture>
  </div>
</body>
</html>
"""


@pytest.fixture
def snapshot_page_html() -> str:
    return SNAPSHOT_HTML
