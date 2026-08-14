"""Turn snapshot HTML into a cleaned article body plus an image inventory.

Strategy: drop archive.today chrome and page furniture, pick the main
content block, keep the semantic blocks (headings, paragraphs, lists,
tables, quotes, code, images), and rewrite image <src>s to deterministic
placeholders that the EPUB builder later maps to downloaded files.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

_MIN_CONTENT_CHARS = 400


@dataclass
class ImageRef:
    src: str
    alt: str
    placeholder: str  # e.g. "images/0003" — final filename substituted later


@dataclass
class Article:
    title: str
    author: str | None
    language: str
    source_url: str | None
    body: str  # cleaned XHTML fragment (content of <body>)
    images: list[ImageRef] = field(default_factory=list)


_JUNK_SELECTORS = (
    "script, style, noscript, template, iframe, frame, object, embed, canvas, "
    "svg, video, audio, form, input, button, select, textarea, nav, header, "
    "footer, aside"
)

#: id/class tokens that mark furniture (ads, chrome, paywalls, ...).
_JUNK_CLASS_RE = re.compile(
    r"(^|[\s_-])("
    r"ad|ads|advert|sponsor|promo|paywall|subscribe|subscription|newsletter|"
    r"cookie|consent|modal|popup|overlay|social|share|related|recommended|"
    r"comment|comments|masthead|navbar|topbar|toolbar|breadcrumb|pagination|"
    r"sidebar|skip|hidden|sr-only|g-recaptcha"
    r")([\s_-]|$)",
    re.IGNORECASE,
)

#: Small elements that push a subscription: text-based paywall detection.
_PAYWALL_TEXT_RE = re.compile(
    r"\b(subscribe|subscription|subscriber|sign in|sign up|membership|paywall)\b",
    re.IGNORECASE,
)

_CONTENT_SELECTORS = (
    "article",
    "main",
    "[role='main']",
    "#content",
    "#CONTENT",  # archive.today uses uppercase ids
    "#main",
    "#article",
    "#post",
    "#entry",
    ".content",
    ".article",
    ".article_content",
    ".article-content",
    ".article-body",
    ".post",
    ".post-content",
    ".entry",
    ".entry-content",
    ".story",
    ".story-body",
    ".body",
)

_WORDMARK_RE = re.compile(
    r"^\s*archive\.(?:today|is|ph|li|md|vn|fo|yt|wf)\s*$", re.IGNORECASE
)
_TITLE_SUFFIX_RE = re.compile(r"\s*[|\-–]\s*archive\.(?:today|is|ph|li|md|vn|fo|yt|wf)\s*$", re.IGNORECASE)

_IMG_SRC_ATTRS = ("src", "data-src", "data-lazy-src", "data-original", "data-url")
_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "blockquote",
               "pre", "table", "figure", "hr", "dl", "img"}
_INLINE_TAGS = {"a", "strong", "em", "b", "i", "u", "s", "code", "br", "span",
                "sub", "sup", "small", "q", "abbr", "cite", "mark"}


def _remove_archive_chrome(soup: BeautifulSoup) -> None:
    """Drop the archive.today toolbar (wordmark link + header containers)."""
    wordmark = soup.find("a", string=_WORDMARK_RE)
    if wordmark:
        node: Tag | None = wordmark
        for _ in range(6):
            parent = node.parent
            if parent is None or parent.name in ("html", "body"):
                break
            node = parent
        if node is not None:
            node.decompose()
    for selector in (
        "#HEADER",
        "[id^='HEADER']",
        "[class*='toolbar']",
        "[id*='toolbar']",
        "[class*='navbar']",
    ):
        for el in soup.select(selector):
            el.decompose()


def _remove_junk(root: Tag) -> None:
    # Sites nest article hero images inside chrome <header>/<aside> blocks.
    # Hoist the images out first so the image survives the block removal.
    for el in root.select("header, aside"):
        if el.parent is None:
            continue
        for img in list(el.find_all("img")):
            img.extract()
            el.insert_before(img)
    for el in root.select(_JUNK_SELECTORS):
        el.decompose()
    for el in list(root.find_all(True)):
        classes = " ".join((el.attrs or {}).get("class") or [])
        ident = (el.attrs or {}).get("id") or ""
        if _JUNK_CLASS_RE.search(f"{classes} {ident}"):
            el.decompose()
            continue
        if el.name in ("div", "section", "span"):
            text = el.get_text(" ", strip=True)
            if (
                len(text) < 600
                and _PAYWALL_TEXT_RE.search(text)
                and not el.find("img")
                and not el.find("table")
            ):
                el.decompose()


def _pick_content_root(soup: BeautifulSoup) -> Tag:
    best: Tag | None = None
    best_len = 0
    for selector in _CONTENT_SELECTORS:
        for el in soup.select(selector):
            length = len(el.get_text(" ", strip=True))
            if length > best_len:
                best, best_len = el, length
    if best is not None and best_len >= _MIN_CONTENT_CHARS:
        return best
    # Fall back to the whole body (toolbar/chrome already removed).
    return soup.body or soup


def _collect_images(root: Tag, images: list[ImageRef], base_url: str | None = None) -> None:
    for img in list(root.find_all("img")):
        src = next(((img.attrs or {}).get(a) for a in _IMG_SRC_ATTRS if (img.attrs or {}).get(a)), None)
        if not src:
            srcset = (img.attrs or {}).get("srcset")
            if srcset:
                candidates = [
                    p.strip().split() for p in srcset.split(",") if p.strip()
                ]
                candidates.sort(
                    key=lambda c: int(c[1][:-1]) if len(c) > 1 and c[1].endswith("w") else 0
                )
                src = candidates[-1][0] if candidates else None
        if not src:
            # <picture>: the URL lives on sibling <source srcset> elements.
            # Some sites nest brokenly, so walk up to find the picture.
            picture = None
            node = img.parent
            for _ in range(4):
                if node is None:
                    break
                if node.name == "picture":
                    picture = node
                    break
                node = node.parent
            if picture is not None:
                for source in picture.find_all("source"):
                    ss = (source.attrs or {}).get("srcset")
                    if not ss:
                        continue
                    candidates = [
                        p.strip().split() for p in ss.split(",") if p.strip()
                    ]
                    candidates.sort(
                        key=lambda c: int(c[1][:-1]) if len(c) > 1 and c[1].endswith("w") else 0
                    )
                    src = candidates[-1][0] if candidates else None
                    if src:
                        break
        if not src or src.startswith("data:"):
            img.decompose()
            continue
        if src.startswith("//"):
            src = "https:" + src
        elif base_url and not src.startswith(("http://", "https://")):
            src = urljoin(base_url, src)
        placeholder = f"images/{len(images):04d}"
        alt = (img.attrs or {}).get("alt") or ""
        images.append(ImageRef(src=src, alt=alt, placeholder=placeholder))
        img.attrs = {"src": placeholder, "alt": alt}


def _resolve_title(soup: BeautifulSoup, root: Tag) -> str:
    if soup.title and soup.title.get_text(strip=True):
        title = _TITLE_SUFFIX_RE.sub("", soup.title.get_text(strip=True)).strip()
        if title:
            return title
    h1 = root.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(" ", strip=True).strip()
    return "Archived page"


def _resolve_author(soup: BeautifulSoup) -> str | None:
    for meta in soup.find_all("meta"):
        if ((meta.attrs or {}).get("name") or "").lower() == "author":
            value = ((meta.attrs or {}).get("content") or "").strip()
            if value:
                return value
    for selector in ("[rel='author']", ".byline", ".author", "[class*='byline']"):
        el = soup.select_one(selector)
        if el:
            text = el.get_text(" ", strip=True)
            if text and len(text) < 120:
                return text
    # Byline link to an author/profile page (e.g. Caravan's /author/<slug>).
    for a in soup.find_all("a"):
        href = (a.attrs or {}).get("href") or ""
        if re.search(r"/(author|authors|writer|writers|contributor|contributors)/", href, re.IGNORECASE):
            text = a.get_text(" ", strip=True)
            if text and len(text) < 80 and "author" not in text.lower() and "writer" not in text.lower():
                return text
    m = re.search(r'"author"\s*:\s*\{[^{}]*"name"\s*:\s*"([^"]+)"', soup.decode())
    if m:
        return m.group(1)
    return None


def _resolve_language(soup: BeautifulSoup) -> str:
    html = soup.find("html")
    if html and (html.attrs or {}).get("lang"):
        return html["lang"].lower().split("-")[0]
    return "en"


def _resolve_source_url(soup: BeautifulSoup, hint: str | None) -> str | None:
    # On archive.today snapshots the toolbar's "Saved from" box carries the
    # original URL; canonical/meta tags are rewritten to the archive itself.
    header = soup.select_one("#HEADER")
    if header is not None:
        for inp in header.find_all("input"):
            value = (inp.attrs or {}).get("value") or ""
            if value.startswith("http://") or value.startswith("https://"):
                return value
    for el in soup.find_all("link"):
        if ((el.attrs or {}).get("rel") or [None])[0] == "canonical" and (el.attrs or {}).get("href"):
            return el["href"]
    for meta in soup.find_all("meta"):
        if ((meta.attrs or {}).get("property") or "").lower() == "og:url" and meta.get("content"):
            return meta["content"]
    return hint or None


def _is_archive_snapshot(soup: BeautifulSoup) -> bool:
    if soup.find("a", string=_WORDMARK_RE):
        return True
    return bool(soup.select_one("#HEADER, [class*='toolbar']"))


def _jsonld_article_body(soup: BeautifulSoup) -> str | None:
    """Full article text from embedded JSON-LD when the visible DOM is thin."""
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            body = item.get("articleBody")
            if isinstance(body, str) and len(body) > _MIN_CONTENT_CHARS:
                return body
    return None


def _paragraphs_from_text(text: str) -> str:
    parts = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    return "".join(f"<p>{p}</p>" for p in parts)


def extract_article(
    html: str, *, source_url: str | None = None, base_url: str | None = None
) -> Article:
    soup = BeautifulSoup(html, "lxml")
    # The lxml parser can emit tags with attrs=None; normalize so .get() works.
    for el in soup.find_all(True):
        if el.attrs is None:
            el.attrs = {}

    # Resolve metadata and capture JSON-LD BEFORE junk removal: the toolbar
    # carries the original URL, and script tags (JSON-LD) get stripped.
    canonical = _resolve_source_url(soup, source_url)
    author = _resolve_author(soup)
    jsonld_body = _jsonld_article_body(soup)

    if _is_archive_snapshot(soup):
        _remove_archive_chrome(soup)
    _remove_junk(soup)

    root = _pick_content_root(soup)
    images: list[ImageRef] = []
    _collect_images(root, images, base_url)

    title = _resolve_title(soup, root)
    language = _resolve_language(soup)

    text_len = len(root.get_text(" ", strip=True))
    body_text = jsonld_body if text_len < _MIN_CONTENT_CHARS else ""

    if body_text:
        body = _paragraphs_from_text(body_text)
        images = []
    else:
        # Anchor headings for TOC sub-entries.
        for idx, heading in enumerate(root.find_all(["h2", "h3"])):
            if not (heading.attrs or {}).get("id"):
                heading["id"] = f"sec-{idx}"
        for a in root.find_all("a"):
            href = (a.attrs or {}).get("href") or ""
            if href.startswith("javascript:") or href.strip() == "":
                a.unwrap()
        for el in root.find_all(True):
            if "style" in (el.attrs or {}):
                del el.attrs["style"]
            if (
                el.name in _INLINE_TAGS
                or el.name in _BLOCK_TAGS
                or el.name
                in ("li", "tr", "td", "th", "thead", "tbody", "tfoot",
                    "caption", "col", "colgroup", "dt", "dd", "figcaption",
                    "option")
            ):
                continue
            # Non-semantic wrapper (div/section/span): unwrap to flatten the
            # document for EPUB layout.
            el.unwrap()
        body = root.decode_contents()

    return Article(
        title=title,
        author=author,
        language=language,
        source_url=canonical,
        body=body,
        images=images,
    )
