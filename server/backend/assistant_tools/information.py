from __future__ import annotations

import re
from typing import Any

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor,
    function_exponentiation,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from config import (
    FETCH_MAX_CONTENT_CHARS,
    FETCH_MAX_ITEMS,
    FETCH_TIMEOUT,
    WEB_SEARCH_FETCH_LIMIT,
    WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_SOURCE,
    WEB_SEARCH_TIMEOUT,
)
from content_fetch_tool import fetch_url_list, resolve_result_url
from web_search_tool import web_search as no_key_web_search

from assistant_tools.common import build_llm_documents, extract_domain

CALCULATOR_TRANSFORMATIONS = standard_transformations + (
    implicit_multiplication_application,
    function_exponentiation,
    convert_xor,
)
CALCULATOR_LOCALS = {
    "abs": sp.Abs,
    "Abs": sp.Abs,
    "acos": sp.acos,
    "asin": sp.asin,
    "atan": sp.atan,
    "ceil": sp.ceiling,
    "cos": sp.cos,
    "e": sp.E,
    "E": sp.E,
    "exp": sp.exp,
    "floor": sp.floor,
    "ln": sp.log,
    "log": sp.log,
    "pi": sp.pi,
    "pow": lambda base, exponent: base**exponent,
    "round": lambda value, digits=0: round(float(value), int(digits)),
    "sin": sp.sin,
    "sqrt": sp.sqrt,
    "tan": sp.tan,
}
QUERY_STOPWORDS = {
    "gia",
    "giá",
    "hom",
    "hôm",
    "nay",
    "ti",
    "tỉ",
    "ty",
    "tỷ",
    "la",
    "là",
    "bao",
    "nhiêu",
    "tra",
    "cứu",
    "thong",
    "thông",
    "tin",
    "hien",
    "hiện",
    "tai",
    "tại",
}
PASSAGE_SIGNAL_WORDS = (
    "cập nhật",
    "hôm nay",
    "mua vào",
    "bán ra",
    "giá vàng",
    "tỷ giá",
    "usd",
    "vnd",
    "sjc",
    "pnj",
    "doji",
    "ounce",
    "lượng",
    "đồng",
)
AUTHORITY_HINTS = (
    ".gov",
    ".edu",
    "vietcombank",
    "bidv",
    "vietinbank",
    "techcombank",
    "acb",
    "agribank",
    "pnj",
    "sjc",
    "doji",
    "kitco",
)
PASSAGE_NOISE_MARKERS = (
    "<svg",
    "xmlns=",
    "fill-rule",
    "clip-rule",
    "viewbox=",
    "vui lòng nhập tối thiểu",
    "cookie",
)
GOLD_SPECIFIC_TERMS = {
    "miếng",
    "vang mieng",
    "nhẫn",
    "nhan",
    "sjc",
    "pnj",
    "doji",
    "9999",
    "24k",
    "18k",
    "thế giới",
    "the gioi",
    "quốc tế",
    "quoc te",
    "trong nước",
    "trong nuoc",
}
USD_SPECIFIC_TERMS = {
    "mua vào",
    "mua vao",
    "bán ra",
    "ban ra",
    "trung tâm",
    "trung tam",
    "chợ đen",
    "cho den",
    "ngân hàng",
    "ngan hang",
    "vietcombank",
    "bidv",
    "acb",
    "techcombank",
    "tự do",
    "tu do",
}


def _format_number(value: int | float) -> str:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return format(value, ".12g")


def _normalize_math_expression(expression: str) -> str:
    normalized = expression.strip()
    normalized = normalized.replace("×", "*").replace("÷", "/").replace("−", "-")
    normalized = normalized.replace("π", "pi")
    normalized = re.sub(r"\bmod\b", "%", normalized, flags=re.IGNORECASE)
    return normalized


def _query_terms(query: str) -> list[str]:
    normalized = re.sub(r"[^\w\s]", " ", query.lower(), flags=re.UNICODE)
    terms = []
    for token in normalized.split():
        if len(token) <= 1 or token in QUERY_STOPWORDS:
            continue
        terms.append(token)
    return terms


def _split_passages(text: str) -> list[str]:
    chunks = re.split(r"\n{2,}|(?<=[\.\!\?])\s+", text)
    passages = []
    for chunk in chunks:
        normalized = " ".join(chunk.split())
        if len(normalized) >= 35:
            passages.append(normalized)
    return passages


def _passage_score(text: str, query: str) -> int:
    lowered = text.lower()
    if any(marker in lowered for marker in PASSAGE_NOISE_MARKERS):
        return -5
    score = 0
    for term in _query_terms(query):
        if term in lowered:
            score += 4
    if re.search(r"\d", text):
        score += 3
    if re.search(r"\d[\d\.\,]*\s*(đồng|usd|vnd|lượng|ounce|%)", lowered):
        score += 5
    if "/" in text and any(token in lowered for token in ("usd", "vnd", "đồng")):
        score += 3
    if "mua vào" in lowered:
        score += 3
    if "bán ra" in lowered:
        score += 3
    if any(marker in lowered for marker in PASSAGE_SIGNAL_WORDS):
        score += 2
    if "cập nhật lúc" in lowered or re.search(r"\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}", lowered):
        score += 2
    if len(text) > 320:
        score -= 1
    return score


def _domain_authority_score(domain: str) -> int:
    lowered = domain.lower()
    score = 0
    if lowered.endswith(".gov.vn") or ".gov." in lowered:
        score += 8
    if any(marker in lowered for marker in AUTHORITY_HINTS):
        score += 5
    return score


def _result_relevance_score(result: dict[str, Any], query: str) -> int:
    title = str(result.get("title", ""))
    snippet = str(result.get("snippet", ""))
    domain = str(result.get("domain", ""))
    combined = f"{title} {snippet}"
    score = _passage_score(combined, query)
    score += _domain_authority_score(domain)
    return score


def _build_query_focused_content(text: str, query: str, max_chars: int = 1200) -> tuple[str, str]:
    passages = _split_passages(text)
    if not passages:
        normalized = " ".join((text or "").split())
        excerpt = normalized[:320].strip()
        return normalized[:max_chars].strip(), excerpt

    ranked = sorted(
        passages,
        key=lambda passage: (_passage_score(passage, query), len(passage)),
        reverse=True,
    )
    selected = [passage for passage in ranked if _passage_score(passage, query) > 0][:3]
    if not selected:
        selected = passages[:2]

    focused_content = "\n\n".join(selected)[:max_chars].strip()
    focused_excerpt = selected[0][:320].strip() if selected else ""
    return focused_content, focused_excerpt


def _normalize_query_text(value: str) -> str:
    return " ".join((value or "").lower().split())


def _content_blob(results: list[dict[str, Any]], content_items: list[dict[str, Any]]) -> str:
    parts = []
    for result in results[:5]:
        parts.extend(
            [
                str(result.get("title", "")),
                str(result.get("snippet", "")),
                str(result.get("domain", "")),
            ]
        )

    for item in content_items[:5]:
        parts.extend(
            [
                str(item.get("title", "")),
                str(item.get("focused_excerpt") or item.get("excerpt", "")),
                str(item.get("focused_content", ""))[:600],
                str(item.get("domain", "")),
            ]
        )

    return " ".join(parts).lower()


def _detect_information_ambiguity(
    query: str,
    results: list[dict[str, Any]],
    content_items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    normalized_query = _normalize_query_text(query)
    blob = _content_blob(results, content_items)

    if "vàng" in normalized_query or "vang" in normalized_query:
        if not any(term in normalized_query for term in GOLD_SPECIFIC_TERMS):
            options = []
            if any(term in blob for term in ("sjc", "vàng miếng", "vang mieng")):
                options.append("giá vàng miếng SJC trong nước")
            if any(term in blob for term in ("nhẫn", "nhan", "9999", "24k", "18k")):
                options.append("giá vàng nhẫn hoặc vàng 9999 trong nước")
            if any(term in blob for term in ("thế giới", "the gioi", "ounce", "kitco")):
                options.append("giá vàng thế giới")

            if len(options) >= 2:
                return {
                    "should_clarify": True,
                    "reason": "Query về vàng có nhiều hệ quy chiếu khác nhau.",
                    "question": "Bạn muốn xem giá vàng miếng SJC, vàng nhẫn/9999 trong nước, hay giá vàng thế giới?",
                    "missing_fields": ["gold_reference_type"],
                    "options": options[:3],
                }

    if any(term in normalized_query for term in ("usd", "đô", "do", "tỷ giá", "ty gia")):
        if not any(term in normalized_query for term in USD_SPECIFIC_TERMS):
            options = []
            if any(term in blob for term in ("mua vào", "mua vao")):
                options.append("giá USD mua vào")
            if any(term in blob for term in ("bán ra", "ban ra")):
                options.append("giá USD bán ra")
            if any(term in blob for term in ("trung tâm", "trung tam")):
                options.append("tỷ giá trung tâm")
            if any(term in blob for term in ("vietcombank", "bidv", "acb", "techcombank")):
                options.append("tỷ giá USD tại ngân hàng")
            if any(term in blob for term in ("chợ đen", "cho den", "tự do", "tu do")):
                options.append("tỷ giá USD tự do/chợ đen")

            deduped_options = []
            for option in options:
                if option not in deduped_options:
                    deduped_options.append(option)

            if len(deduped_options) >= 2:
                return {
                    "should_clarify": True,
                    "reason": "Query về USD có nhiều hệ quy chiếu như mua vào, bán ra, ngân hàng, trung tâm.",
                    "question": "Bạn muốn xem giá USD mua vào, bán ra, tỷ giá trung tâm, hay tỷ giá ở ngân hàng?",
                    "missing_fields": ["usd_reference_type"],
                    "options": deduped_options[:4],
                }

    return None


def _prepare_query_focused_items(
    content_items: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    prepared = []
    for item in content_items:
        item_copy = dict(item)
        if item_copy.get("status") == "success":
            focused_content, focused_excerpt = _build_query_focused_content(
                str(item_copy.get("content", "")),
                query=query,
            )
            item_copy["focused_content"] = focused_content
            item_copy["focused_excerpt"] = focused_excerpt or item_copy.get("excerpt", "")
            item_copy["relevance_score"] = (
                _passage_score(item_copy.get("title", ""), query)
                + _passage_score(focused_excerpt, query)
                + _domain_authority_score(str(item_copy.get("domain", "")))
            )
        prepared.append(item_copy)

    prepared.sort(key=lambda item: int(item.get("relevance_score", 0)), reverse=True)
    return prepared


def _build_summary_candidates(
    results: list[dict[str, Any]],
    content_items: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    candidates = []

    for item in content_items:
        if item.get("status") != "success":
            continue
        excerpt = item.get("focused_excerpt") or item.get("excerpt") or ""
        if not excerpt:
            continue
        candidates.append(
            {
                "domain": item.get("domain", ""),
                "title": item.get("title", ""),
                "url": item.get("final_url") or item.get("resolved_url") or item.get("requested_url"),
                "excerpt": excerpt,
                "score": int(item.get("relevance_score", 0)),
            }
        )

    for result in results:
        candidates.append(
            {
                "domain": result.get("domain", ""),
                "title": result.get("title", ""),
                "url": result.get("link"),
                "excerpt": result.get("snippet", ""),
                "score": _result_relevance_score(result, query),
            }
        )

    ranked = sorted(candidates, key=lambda item: int(item.get("score", 0)), reverse=True)
    deduped = []
    seen_urls: set[str] = set()
    for item in ranked:
        url = str(item.get("url", "") or "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        deduped.append(item)
        if len(deduped) >= 5:
            break
    return deduped


def _evaluate_expression(expression: str) -> tuple[str, sp.Expr, int | float, str]:
    normalized = _normalize_math_expression(expression)
    parsed = parse_expr(
        normalized,
        local_dict=CALCULATOR_LOCALS,
        transformations=CALCULATOR_TRANSFORMATIONS,
        evaluate=True,
    )
    simplified = sp.simplify(parsed)

    if getattr(simplified, "free_symbols", set()):
        raise ValueError("Expression phải cho ra một kết quả số cụ thể")

    if simplified.is_real is False:
        raise ValueError("Hiện chỉ hỗ trợ kết quả số thực")

    if getattr(simplified, "is_Integer", False):
        numeric_result: int | float = int(simplified)
    else:
        numeric_result = float(sp.N(simplified, 15))

    return normalized, simplified, numeric_result, _format_number(numeric_result)


def web_search_with(
    query: str,
    max_results: int = WEB_SEARCH_MAX_RESULTS,
    *,
    web_search_fn,
    fetch_url_list_fn,
    resolve_result_url_fn,
) -> dict[str, Any]:
    """
    Search the web and fetch readable content from top results so the LLM can synthesize.
    """
    try:
        data = web_search_fn(
            query=query,
            max_results=max_results,
            timeout=WEB_SEARCH_TIMEOUT,
            source=WEB_SEARCH_SOURCE,
        )
        raw_results = data.get("results", [])
        results = []
        for result in raw_results:
            link = result.get("resolved_url") or resolve_result_url_fn(result.get("url", ""))
            title = result.get("title", "")
            snippet = result.get("snippet", "")
            results.append(
                {
                    "title": title,
                    "snippet": snippet,
                    "link": link,
                    "domain": extract_domain(link),
                }
            )

        ranked_results = sorted(results, key=lambda item: _result_relevance_score(item, query), reverse=True)
        fetch_targets = [result["link"] for result in ranked_results[:WEB_SEARCH_FETCH_LIMIT] if result.get("link")]
        fetch_data = fetch_url_list_fn(
            fetch_targets,
            timeout=FETCH_TIMEOUT,
            max_content_chars=FETCH_MAX_CONTENT_CHARS,
            max_items=min(WEB_SEARCH_FETCH_LIMIT, FETCH_MAX_ITEMS),
        )
        content_items = _prepare_query_focused_items(fetch_data.get("items", []), query=query)
        llm_documents = build_llm_documents(content_items)
        summary_candidates = _build_summary_candidates(ranked_results, content_items, query)
        ambiguity_hint = _detect_information_ambiguity(query, ranked_results, content_items)

        primary_result = ranked_results[0] if ranked_results else None
        answer = ""
        if summary_candidates:
            answer = summary_candidates[0].get("excerpt", "")
        elif llm_documents:
            answer = llm_documents[0].get("excerpt", "") or llm_documents[0].get("content", "")
        elif primary_result:
            answer = primary_result.get("snippet") or primary_result.get("title", "")
        device_payload = {
            "type": "search_results",
            "query": query,
            "status": "ok" if results else "empty",
            "source": data.get("source", WEB_SEARCH_SOURCE),
            "answer_text": answer,
            "top_result": primary_result,
            "results": ranked_results[:max_results],
            "content_items": content_items,
            "summary_candidates": summary_candidates,
            "ambiguity_hint": ambiguity_hint,
        }

        return {
            "status": "success",
            "answer": answer,
            "results": ranked_results,
            "primary_result": primary_result,
            "content_items": content_items,
            "llm_documents": llm_documents,
            "summary_candidates": summary_candidates,
            "ambiguity_hint": ambiguity_hint,
            "query": query,
            "source": data.get("source", WEB_SEARCH_SOURCE),
            "message": (
                f"Tìm thấy {len(ranked_results)} kết quả từ {data.get('source', WEB_SEARCH_SOURCE)} "
                f"và đọc {len(llm_documents)} nguồn"
            ),
            "device_payload": device_payload,
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Web search error: {str(exc)}",
        }


def web_search(query: str, max_results: int = WEB_SEARCH_MAX_RESULTS) -> dict[str, Any]:
    return web_search_with(
        query=query,
        max_results=max_results,
        web_search_fn=no_key_web_search,
        fetch_url_list_fn=fetch_url_list,
        resolve_result_url_fn=resolve_result_url,
    )


def fetch_content_with(
    urls: list[str],
    max_items: int = FETCH_MAX_ITEMS,
    max_content_chars: int = FETCH_MAX_CONTENT_CHARS,
    *,
    fetch_url_list_fn,
) -> dict[str, Any]:
    """
    Fetch readable text content from a list of URLs.
    """
    try:
        fetch_data = fetch_url_list_fn(
            urls,
            timeout=FETCH_TIMEOUT,
            max_content_chars=max_content_chars,
            max_items=max_items,
        )
        content_items = fetch_data.get("items", [])
        llm_documents = build_llm_documents(content_items)

        return {
            "status": "success",
            "urls": urls,
            "content_items": content_items,
            "llm_documents": llm_documents,
            "message": f"Đã đọc {len(llm_documents)} nguồn nội dung",
            "device_payload": {
                "type": "fetched_content",
                "status": "ok" if llm_documents else "empty",
                "urls": urls,
                "content_items": content_items,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Fetch content error: {str(exc)}",
        }


def fetch_content(
    urls: list[str],
    max_items: int = FETCH_MAX_ITEMS,
    max_content_chars: int = FETCH_MAX_CONTENT_CHARS,
) -> dict[str, Any]:
    return fetch_content_with(
        urls=urls,
        max_items=max_items,
        max_content_chars=max_content_chars,
        fetch_url_list_fn=fetch_url_list,
    )


def calculator(expression: str) -> dict[str, Any]:
    """
    Evaluate mathematical expressions safely and return a compact edge payload.
    """
    try:
        normalized_expression, exact_result, numeric_result, formatted_result = _evaluate_expression(expression)

        return {
            "status": "success",
            "expression": expression,
            "normalized_expression": normalized_expression,
            "result": numeric_result,
            "exact_result": str(exact_result),
            "formatted_result": formatted_result,
            "message": f"Kết quả là {formatted_result}",
            "device_payload": {
                "type": "calculation_result",
                "expression": expression,
                "normalized_expression": normalized_expression,
                "result": numeric_result,
                "formatted_result": formatted_result,
                "exact_result": str(exact_result),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Calculation error: {str(exc)}",
        }
