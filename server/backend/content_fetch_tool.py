from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
import re

import requests
from requests.exceptions import SSLError

from config import FETCH_MAX_CONTENT_CHARS, FETCH_MAX_ITEMS, FETCH_TIMEOUT

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
SKIP_TAGS = {"script", "style", "noscript", "svg", "footer", "nav"}
BLOCK_TAGS = {
    "article",
    "aside",
    "blockquote",
    "br",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "p",
    "section",
}
NOISE_SUBSTRINGS = (
    "<svg",
    "xmlns=",
    "fill-rule",
    "clip-rule",
    "viewbox=",
    "cookie",
    "vui lòng nhập tối thiểu",
    "cám ơn quý khách đã đăng ký",
    "có lỗi xảy ra",
    "{time}",
    "{date}",
)


def _normalize_space(value: str) -> str:
    return " ".join(unescape(value).split())


def _is_noise_paragraph(text: str) -> bool:
    lowered = text.lower()
    if any(marker in lowered for marker in NOISE_SUBSTRINGS):
        return True
    if text.count("<") >= 2 or text.count(">") >= 2:
        return True
    return False


def _extract_domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.replace("www.", "")


def resolve_result_url(url: str) -> str:
    if not url:
        return ""

    normalized = url.strip()
    if normalized.startswith("//"):
        normalized = f"https:{normalized}"

    parsed = urlparse(normalized)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        uddg = parse_qs(parsed.query).get("uddg", [""])[0]
        if uddg:
            return unquote(uddg)

    return normalized


class ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return

        if self._skip_depth:
            return

        if tag == "title":
            self._in_title = True
        if tag in BLOCK_TAGS:
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return

        if self._skip_depth:
            return

        if tag == "title":
            self._in_title = False
        if tag in BLOCK_TAGS:
            self._text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return

        if self._in_title:
            self._title_parts.append(data)
        self._text_parts.append(data)

    @property
    def title(self) -> str:
        return _normalize_space("".join(self._title_parts))

    @property
    def content(self) -> str:
        raw = "".join(self._text_parts)
        raw = re.sub(r"\n\s*\n+", "\n\n", raw)
        paragraphs = []
        for piece in raw.split("\n"):
            normalized = _normalize_space(piece)
            if len(normalized) >= 40 and not _is_noise_paragraph(normalized):
                paragraphs.append(normalized)
        compact = "\n\n".join(paragraphs)
        return compact.strip()


def _extract_content_from_html(html: str, max_chars: int) -> tuple[str, str]:
    parser = ReadableHTMLParser()
    parser.feed(html)
    content = parser.content[:max_chars].strip()
    return parser.title, content


def fetch_url_content(
    url: str,
    *,
    timeout: int = FETCH_TIMEOUT,
    max_content_chars: int = FETCH_MAX_CONTENT_CHARS,
) -> dict[str, Any]:
    resolved_url = resolve_result_url(url)
    try:
        response = requests.get(
            resolved_url,
            timeout=timeout,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            allow_redirects=True,
        )
        insecure_tls = False
    except SSLError:
        response = requests.get(
            resolved_url,
            timeout=timeout,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            allow_redirects=True,
            verify=False,
        )
        insecure_tls = True
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "").lower()
    final_url = response.url or resolved_url
    domain = _extract_domain(final_url)

    if "text/html" in content_type or content_type == "":
        title, content = _extract_content_from_html(response.text, max_content_chars)
    elif "text/plain" in content_type:
        title = ""
        content = _normalize_space(response.text)[:max_content_chars]
    else:
        return {
            "status": "unsupported",
            "requested_url": url,
            "resolved_url": resolved_url,
            "final_url": final_url,
            "domain": domain,
            "content_type": content_type,
            "message": f"Unsupported content type: {content_type}",
        }

    excerpt = content[:320].strip()
    return {
        "status": "success",
        "requested_url": url,
        "resolved_url": resolved_url,
        "final_url": final_url,
        "domain": domain,
        "content_type": content_type or "text/html",
        "title": title,
        "content": content,
        "excerpt": excerpt,
        "content_length": len(content),
        "insecure_tls": insecure_tls,
    }


def fetch_url_list(
    urls: list[str],
    *,
    timeout: int = FETCH_TIMEOUT,
    max_content_chars: int = FETCH_MAX_CONTENT_CHARS,
    max_items: int = FETCH_MAX_ITEMS,
) -> dict[str, Any]:
    items = []
    seen: set[str] = set()

    for url in urls:
        resolved = resolve_result_url(url)
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)

        try:
            item = fetch_url_content(
                resolved,
                timeout=timeout,
                max_content_chars=max_content_chars,
            )
        except Exception as exc:
            item = {
                "status": "error",
                "requested_url": url,
                "resolved_url": resolved,
                "final_url": resolved,
                "domain": _extract_domain(resolved),
                "message": str(exc),
            }

        items.append(item)
        if len(items) >= max_items:
            break

    successful_items = [item for item in items if item.get("status") == "success"]
    return {
        "status": "success",
        "items": items,
        "successful_items": successful_items,
        "count": len(items),
    }
