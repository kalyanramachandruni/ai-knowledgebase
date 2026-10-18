"""Pure HTML/URL helpers for the web crawler: URL normalisation, site scoping and page parsing."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import tldextract
from bs4 import (
    BeautifulSoup,
    CData,
    Comment,
    Declaration,
    Doctype,
    NavigableString,
    ProcessingInstruction,
    Tag,
)

# Bundled Public Suffix List snapshot only — never fetch it over the network at runtime.
_TLD_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True, cache_dir=None)

_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid"}

SKIPPED_EXTENSIONS = (
    ".pdf", ".zip", ".gz", ".tar", ".rar", ".7z", ".exe", ".dmg", ".msi",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".mp3", ".mp4", ".mov", ".avi", ".webm", ".woff", ".woff2", ".ttf",
    ".css", ".js", ".xml", ".json", ".csv", ".xls", ".xlsx", ".doc", ".docx", ".ppt", ".pptx",
)

_ALWAYS_REMOVE = ["script", "style", "noscript", "template", "svg", "iframe", "form", "button", "nav"]
_SITE_CHROME = ["header", "footer", "aside"]
_CONTENT_CONTAINERS = ["article", "main", "section"]
_NOISE_ROLES = {"navigation", "banner", "contentinfo"}
_NOISE_ID_CLASS = re.compile(r"cookie|consent|gdpr", re.IGNORECASE)
# Never strip these via the id/class heuristic — e.g. <body class="cookie-consent-shown"> would wipe the page.
_NOISE_HEURISTIC_EXEMPT = {"html", "body", "main", "article"}
_NON_TEXT_NODES = (Comment, CData, ProcessingInstruction, Declaration, Doctype)

_BLOCK_TAGS = {
    "p", "div", "section", "article", "main", "li", "ul", "ol", "table", "tr",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "dl", "dt", "dd", "figure", "figcaption",
}
_HEADING_LEVELS = {f"h{i}": i for i in range(1, 7)}

_THIN_CONTENT_CHARS = 200
_MD_LINK = re.compile(r"\[((?:\\.|[^\]\\])*)\]\([^)]*\)")
_INLINE_WS = re.compile(r"[ \t\r\n\f\v]+")


@dataclass
class ParsedPage:
    title: str
    plain_text: str
    links: list[str] = field(default_factory=list)
    follow_links: list[str] = field(default_factory=list)
    is_thin_content: bool = False


def normalize_url(url: str, *, keep_query: bool) -> str | None:
    """Canonical form of an http(s) URL, or None for any other scheme / unparseable input."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return None
    host = parts.hostname or ""  # lowercased, userinfo and port removed
    if not host:
        return None
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and not (scheme == "http" and port == 80) and not (scheme == "https" and port == 443):
        netloc = f"{netloc}:{port}"
    path = parts.path.rstrip("/")
    query = ""
    if keep_query and parts.query:
        params = [
            (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
        ]
        query = urlencode(sorted(params))
    return urlunsplit((scheme, netloc, path, query, ""))


def site_key(host: str) -> str:
    """Registrable domain for a host (PSL-aware), e.g. www.bbc.co.uk → bbc.co.uk, foo.github.io → foo.github.io."""
    host = host.lower()
    ext = _TLD_EXTRACT(host)
    return ext.top_domain_under_public_suffix or host


def url_site_key(url: str) -> str:
    return site_key(urlsplit(url).hostname or "")


def has_skipped_extension(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(SKIPPED_EXTENSIONS)


def parse_page(html: str, page_url: str, *, keep_query: bool) -> ParsedPage:
    """Parse a page once: title, markdown-ish plain text with absolute links, and outbound links."""
    soup = BeautifulSoup(html, "lxml")

    base_url = page_url
    base_tag = soup.find("base", href=True)
    if base_tag:
        try:
            base_url = urljoin(page_url, base_tag["href"].strip())
        except ValueError:
            pass

    # Links are collected from the full document before any noise removal.
    links, follow_links = _collect_links(soup, base_url, page_url, keep_query)

    title = _title(soup)

    _remove_noise(soup)
    body = soup.body or soup
    plain_text = _to_markdown(body, base_url)

    visible = _MD_LINK.sub(r"\1", plain_text)
    is_thin = len(visible) < _THIN_CONTENT_CHARS and "<script" in html.lower()

    return ParsedPage(
        title=title,
        plain_text=plain_text,
        links=links,
        follow_links=follow_links,
        is_thin_content=is_thin,
    )


def _collect_links(soup: BeautifulSoup, base_url: str, page_url: str, keep_query: bool) -> tuple[list[str], list[str]]:
    self_url = normalize_url(page_url, keep_query=keep_query)
    page_site = url_site_key(page_url)
    links: list[str] = []
    follow: list[str] = []
    seen: set[str] = set()
    follow_seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#"):
            continue
        try:
            url = normalize_url(urljoin(base_url, href), keep_query=keep_query)
        except ValueError:
            continue
        if url is None or url == self_url:
            continue
        if url not in seen:
            seen.add(url)
            links.append(url)
        rel = a.get("rel") or []
        if isinstance(rel, str):
            rel = rel.split()
        nofollow = any(r.lower() == "nofollow" for r in rel)
        if (
            not nofollow
            and url not in follow_seen
            and not has_skipped_extension(url)
            and url_site_key(url) == page_site
        ):
            follow_seen.add(url)
            follow.append(url)
    return links, follow


def _collapse(text: str) -> str:
    return _INLINE_WS.sub(" ", text).strip()


def _title(soup: BeautifulSoup) -> str:
    if soup.title:
        title = _collapse(soup.title.get_text(" "))
        if title:
            return title
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        title = _collapse(og["content"])
        if title:
            return title
    # Captured before noise removal so a headline <h1> inside <header> still counts.
    h1 = soup.find("h1")
    if h1:
        title = _collapse(h1.get_text(" "))
        if title:
            return title
    return "Untitled"


def _remove_noise(soup: BeautifulSoup) -> None:
    for node in soup.find_all(string=lambda s: isinstance(s, _NON_TEXT_NODES)):
        node.extract()

    doomed: list[Tag] = list(soup.find_all(_ALWAYS_REMOVE))
    for el in soup.find_all(True):
        role = (el.get("role") or "").strip().lower()
        if role in _NOISE_ROLES:
            doomed.append(el)
            continue
        if el.name in _NOISE_HEURISTIC_EXEMPT:
            continue
        cls = el.get("class") or []
        id_class = " ".join([el.get("id") or "", *(cls if isinstance(cls, list) else [cls])])
        if _NOISE_ID_CLASS.search(id_class):
            doomed.append(el)
    for el in soup.find_all(_SITE_CHROME):
        if el.find_parent(_CONTENT_CONTAINERS) is None:
            doomed.append(el)

    for el in doomed:
        if not el.decomposed:
            el.decompose()


def _escape_link_text(text: str) -> str:
    return text.replace("[", "\\[").replace("]", "\\]")


def _escape_link_url(url: str) -> str:
    return url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def _anchor_markdown(a: Tag, base_url: str) -> str:
    text = _collapse(a.get_text(" "))
    href = (a.get("href") or "").strip()
    if not text or not href or href.startswith("#"):
        return text
    try:
        url = urljoin(base_url, href)
        scheme = urlsplit(url).scheme.lower()
    except ValueError:
        return text
    if scheme not in ("http", "https"):
        return text
    return f"[{_escape_link_text(text)}]({_escape_link_url(url)})"


def _to_markdown(root: Tag | BeautifulSoup, base_url: str) -> str:
    """Iterative (explicit stack) DOM → markdown-ish text, safe for arbitrarily deep documents."""
    out: list[str] = []
    pre_blocks: list[str] = []
    # Stack items are either a node to visit or a literal string to emit.
    stack: list[object] = [root]
    while stack:
        item = stack.pop()
        if isinstance(item, str) and not isinstance(item, NavigableString):
            out.append(item)
            continue
        if isinstance(item, NavigableString):
            if not isinstance(item, _NON_TEXT_NODES):
                out.append(_INLINE_WS.sub(" ", str(item)))
            continue
        if not isinstance(item, Tag):
            continue
        name = item.name
        if name == "a":
            out.append(_anchor_markdown(item, base_url))
            continue
        if name == "br":
            out.append("\n")
            continue
        if name == "pre":
            # Placeholder keeps pre whitespace out of the post-processing collapse below.
            pre_blocks.append(item.get_text())
            out.append(f"\n\x00PRE{len(pre_blocks) - 1}\x00\n")
            continue
        if name in _HEADING_LEVELS:
            out.append("\n" + "#" * _HEADING_LEVELS[name] + " ")
            stack.append("\n")
        elif name == "li":
            # No closing newline: the enclosing ul/ol (or the next li) supplies it, keeping lists tight.
            out.append("\n- ")
        elif name in _BLOCK_TAGS:
            out.append("\n")
            stack.append("\n")
        stack.extend(reversed(list(item.children)))

    text = "".join(out)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    lines = [line for line in lines if not re.fullmatch(r"#{1,6}|-", line)]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    for i, block in enumerate(pre_blocks):
        text = text.replace(f"\x00PRE{i}\x00", block.strip("\n"))
    return text
