from __future__ import annotations

from dataclasses import dataclass, asdict
from html import unescape
from html.parser import HTMLParser
from typing import Any
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from content_fetch_tool import resolve_result_url

DEFAULT_SEARCH_SOURCE = os.getenv("WEB_SEARCH_SOURCE", "duckduckgo_html")
SEARCH_URLS = {
    "duckduckgo_html": os.getenv(
        "WEB_SEARCH_URL",
        "https://html.duckduckgo.com/html/",
    ),
    "duckduckgo_lite": "https://lite.duckduckgo.com/lite/",
}
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""


class DuckDuckGoHTMLParser(HTMLParser):
    """Parse DuckDuckGo HTML search results."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[SearchResult] = []
        self._in_result_link = False
        self._in_snippet = False
        self._current_href = ""
        self._current_title: list[str] = []
        self._current_snippet: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        class_name = attrs_dict.get("class", "") or ""

        if tag == "a" and "result__a" in class_name:
            self._in_result_link = True
            self._current_href = attrs_dict.get("href", "") or ""
            self._current_title = []
            self._current_snippet = []

        if tag in {"a", "div"} and "result__snippet" in class_name:
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_result_link:
            title = _normalize_text("".join(self._current_title))
            if title and self._current_href:
                self.results.append(
                    SearchResult(
                        title=title,
                        url=self._current_href,
                        snippet=_normalize_text("".join(self._current_snippet)),
                    )
                )
            self._in_result_link = False
            self._current_href = ""
            self._current_title = []

        if tag in {"a", "div"} and self._in_snippet:
            self._in_snippet = False

    def handle_data(self, data: str) -> None:
        if self._in_result_link:
            self._current_title.append(data)
        elif self._in_snippet and self.results:
            self.results[-1].snippet = _normalize_text(
                f"{self.results[-1].snippet} {data}"
            )


def _normalize_text(text: str) -> str:
    return " ".join(unescape(text).split())


def parse_duckduckgo_results(html: str, max_results: int = 5) -> list[dict[str, str]]:
    """Extract structured results from DuckDuckGo HTML."""
    parser = DuckDuckGoHTMLParser()
    parser.feed(html)
    results = []
    for result in parser.results[:max_results]:
        item = asdict(result)
        item["resolved_url"] = resolve_result_url(item.get("url", ""))
        results.append(item)
    return results


def _fetch_results_html(query: str, source: str, timeout: int) -> str:
    search_url = SEARCH_URLS.get(source, SEARCH_URLS["duckduckgo_html"])
    params = urlencode({"q": query})
    request = Request(
        f"{search_url}?{params}",
        headers={"User-Agent": DEFAULT_USER_AGENT},
    )

    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def web_search(
    query: str,
    max_results: int = 5,
    timeout: int = 10,
    source: str | None = None,
) -> dict[str, Any]:
    """
    Search the web without an API key.

    Returns:
        {
            "query": "...",
            "results": [{"title": "...", "url": "...", "snippet": "..."}],
            "source": "duckduckgo_html"
        }
    """
    selected_source = source or DEFAULT_SEARCH_SOURCE
    last_error: Exception | None = None
    candidates = [selected_source]
    if selected_source != "duckduckgo_lite":
        candidates.append("duckduckgo_lite")

    html = ""
    source_used = selected_source
    for candidate in candidates:
        try:
            html = _fetch_results_html(query=query, source=candidate, timeout=timeout)
            source_used = candidate
            break
        except Exception as exc:
            last_error = exc
    else:
        raise RuntimeError(f"Web search request failed: {last_error}") from last_error

    return {
        "query": query,
        "results": parse_duckduckgo_results(html, max_results=max_results),
        "source": source_used,
    }
