from __future__ import annotations

import bleach
import html
import re


SAFE_HTML_TAGS = ["div", "span", "section", "article", "header", "footer", "main", "p", "br", "h1", "h2", "h3", "h4", "strong", "b", "em", "s", "small", "u", "ul", "ol", "li", "blockquote", "pre", "code", "a", "table", "thead", "tbody", "tr", "th", "td", "img", "hr", "input"]
SAFE_HTML_ATTRIBUTES = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "input": ["type", "checked", "disabled"],
}


def clean_html(value: str) -> str:
    cleaned = bleach.clean(value, tags=SAFE_HTML_TAGS, attributes=SAFE_HTML_ATTRIBUTES, protocols=["http", "https", "mailto"], strip=True)
    return re.sub(r'<a\s+([^>]*href="(?:https?://|mailto:)[^"]+"[^>]*)>', lambda match: f'<a {match.group(1)} target="_blank" rel="noopener noreferrer">', cleaned)


def render_description(value: str) -> str:
    if re.search(r"</?[a-zA-Z][^>]*>", value):
        return clean_html(value)
    return html.escape(value).replace("\n", "<br>")
