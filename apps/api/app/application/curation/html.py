from __future__ import annotations

import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]+")


def strip_storage_format(body_storage_format: str) -> str:
    """Strips Confluence storage-format XHTML tags down to plain text for the
    LLM prompt. Good enough for MVP — a full structured-macro-aware parser
    (tables, panels, ADF) is a future improvement, not needed for free-text
    SOP/policy pages."""

    text = _TAG_RE.sub(" ", body_storage_format)
    text = html.unescape(text)
    text = _WHITESPACE_RE.sub(" ", text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
