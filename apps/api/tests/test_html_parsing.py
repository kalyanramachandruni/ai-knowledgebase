from app.infrastructure.crawl.html_parsing import normalize_url, parse_page, site_key

PAGE = "https://www.example.no/docs/guide"


def _parse(body: str, head: str = "", url: str = PAGE, keep_query: bool = False):
    return parse_page(f"<html><head>{head}</head><body>{body}</body></html>", url, keep_query=keep_query)


# ── normalize_url ─────────────────────────────────────────────────────────────

def test_normalize_url_collapses_equivalent_forms():
    variants = ["HTTPS://Example.no:443/a/", "https://example.no/a", "https://user@example.no/a#x"]
    assert {normalize_url(v, keep_query=False) for v in variants} == {"https://example.no/a"}


def test_normalize_url_root_and_non_default_port():
    assert normalize_url("https://example.no/", keep_query=False) == "https://example.no"
    assert normalize_url("http://example.no:80/", keep_query=False) == "http://example.no"
    assert normalize_url("http://example.no:8080/x/", keep_query=False) == "http://example.no:8080/x"


def test_normalize_url_rejects_non_http_schemes():
    for url in ["mailto:x@y.no", "tel:+4712345678", "JavaScript:void(0)", "ftp://example.no/f"]:
        assert normalize_url(url, keep_query=False) is None


def test_normalize_url_query_handling():
    url = "https://example.no/p?b=2&utm_source=x&a=1"
    assert normalize_url(url, keep_query=False) == "https://example.no/p"
    assert normalize_url(url, keep_query=True) == "https://example.no/p?a=1&b=2"
    assert normalize_url("https://example.no/p?utm_medium=x&fbclid=1", keep_query=True) == "https://example.no/p"


# ── site_key ──────────────────────────────────────────────────────────────────

def test_site_key_uses_public_suffix_list():
    assert site_key("www.bbc.co.uk") == "bbc.co.uk"
    assert site_key("foo.github.io") == "foo.github.io"
    assert site_key("adressesok.posten.no") == "posten.no"
    assert site_key("www.posten.no") == "posten.no"


# ── parse_page: links ─────────────────────────────────────────────────────────

def test_links_in_text_are_absolute_against_page_url():
    page = _parse('<p>See <a href="../pricing">pricing</a>.</p>')
    assert "[pricing](https://www.example.no/pricing)" in page.plain_text


def test_links_resolve_against_base_href():
    page = _parse('<p><a href="pricing">pricing</a></p>', head='<base href="https://cdn.example.no/v2/">')
    assert "[pricing](https://cdn.example.no/v2/pricing)" in page.plain_text
    assert "https://cdn.example.no/v2/pricing" in page.links


def test_non_http_links_render_as_text_only():
    page = _parse('<p><a href="mailto:x@y.no">Mail</a> <a href="JavaScript:void(0)">Click</a> '
                  '<a href="#top">Top</a></p>')
    assert page.plain_text == "Mail Click Top"


def test_link_markdown_is_escaped():
    page = _parse('<p><a href="/wiki/Foo_(bar)">see [1] here</a></p>')
    assert "[see \\[1\\] here](https://www.example.no/wiki/Foo_%28bar%29)" in page.plain_text


def test_follow_links_filtering():
    page = _parse(
        '<a href="/a">a</a>'
        '<a href="https://sub.example.no/b">b</a>'
        '<a href="https://other.no/c">c</a>'
        '<a href="/d" rel="nofollow">d</a>'
        '<a href="/file.PDF">pdf</a>'
        '<a href="/a/">a again</a>'
        '<a href="/docs/guide/">self</a>'
    )
    assert page.follow_links == ["https://www.example.no/a", "https://sub.example.no/b"]
    assert page.links == [
        "https://www.example.no/a",
        "https://sub.example.no/b",
        "https://other.no/c",
        "https://www.example.no/d",
        "https://www.example.no/file.PDF",
    ]


def test_nav_links_are_recorded_even_though_nav_text_is_removed():
    page = _parse('<nav><a href="/menu">Menu</a></nav><p>Body</p>')
    assert "https://www.example.no/menu" in page.links
    assert "Menu" not in page.plain_text


# ── parse_page: text ──────────────────────────────────────────────────────────

def test_comments_are_dropped():
    page = _parse("<p>Visible<!-- secret tracking note --></p>")
    assert "secret" not in page.plain_text
    assert page.plain_text == "Visible"


def test_block_elements_are_separated_and_structured():
    page = _parse("<p>One</p><p>Two</p><h2>Heading</h2><ul><li>first</li><li>second</li></ul>")
    assert page.plain_text == "One\n\nTwo\n\n## Heading\n\n- first\n- second"


def test_pre_keeps_whitespace():
    page = _parse("<p>Code:</p><pre>def f():\n    return  1</pre>")
    assert "def f():\n    return  1" in page.plain_text


def test_article_header_is_kept_site_header_removed():
    page = _parse(
        "<header><h1>Site name</h1></header><nav>Menu</nav>"
        "<article><header><h1>Headline</h1></header><p>Story</p></article>"
        "<footer>Copyright</footer>"
    )
    assert "Headline" in page.plain_text
    assert "Site name" not in page.plain_text
    assert "Menu" not in page.plain_text
    assert "Copyright" not in page.plain_text


def test_noise_elements_removed():
    page = _parse(
        "<p>Keep</p><noscript>Enable JS</noscript><svg><text>icon</text></svg>"
        "<form><label>Email</label></form><div role='navigation'>Crumbs</div>"
        "<div id='cookie-banner'>We use cookies</div><div class='Consent-modal'>Agree</div>"
    )
    assert page.plain_text == "Keep"


def test_cookie_heuristic_does_not_remove_body():
    html = "<html><body class='cookie-consent-shown'><p>Content</p></body></html>"
    assert parse_page(html, PAGE, keep_query=False).plain_text == "Content"


def test_deeply_nested_document_does_not_recurse():
    html = "<html><body>" + "<div>" * 5000 + "deep" + "</div>" * 5000 + "</body></html>"
    assert parse_page(html, PAGE, keep_query=False).plain_text == "deep"


# ── parse_page: title ─────────────────────────────────────────────────────────

def test_title_whitespace_collapsed():
    assert _parse("<p>x</p>", head="<title>\n  Foo\n   Bar </title>").title == "Foo Bar"


def test_title_falls_back_to_og_title_then_h1_inside_header():
    assert _parse("<p>x</p>", head='<meta property="og:title" content="OG Title">').title == "OG Title"
    assert _parse("<header><h1>Headline</h1></header><p>x</p>").title == "Headline"
    assert _parse("<p>x</p>").title == "Untitled"


# ── parse_page: thin content ──────────────────────────────────────────────────

def test_spa_shell_is_thin_content():
    page = _parse('<div id="root"></div><script src="/app.js"></script>')
    assert page.is_thin_content is True


def test_article_is_not_thin_content():
    page = _parse("<article><p>" + "Real sentence with content. " * 20 + "</p></article><script>x()</script>")
    assert page.is_thin_content is False
