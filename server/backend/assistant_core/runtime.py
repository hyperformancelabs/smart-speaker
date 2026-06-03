from __future__ import annotations

from functools import lru_cache
from types import SimpleNamespace
from typing import Any

from config import GOOGLE_API_KEY, LLM_MODEL
from assistant_tools.registry import TOOL_FUNCTIONS

from assistant_core.nodes import (
    chat_node,
    conversation_agent,
    execute_tools,
    format_output,
    handle_tool_results,
    information_query_agent,
    load_user_profile,
    log_interaction,
    media_agent,
    personalization_agent,
    productivity_agent,
)
from assistant_core.state import LLMContext, LLMState
from assistant_core.wrapper import LLMWrapper


INTENT_TO_HANDLER = {
    "media": media_agent,
    "information_query": information_query_agent,
    "productivity": productivity_agent,
    "personalization": personalization_agent,
    "conversation": conversation_agent,
}


def _build_initial_state(payload: dict[str, Any]) -> LLMState:
    return {
        "user_id": payload.get("user_id", ""),
        "nfc_tag_id": payload.get("nfc_tag_id", ""),
        "text_input": payload.get("text_input") or payload.get("stt_text", ""),
        # Context now comes from session_state.active_task/conversation_task.
        # We intentionally ignore top-K message windows from callers.
        "messages": [],
        "session_state": payload.get("session_state", {}),
    }


def _build_runtime() -> SimpleNamespace:
    llm = LLMWrapper(model=LLM_MODEL, api_key=GOOGLE_API_KEY)
    context = LLMContext(
        llm=llm,
        tools=TOOL_FUNCTIONS,
        db=None,
        api_client=None,
    )
    return SimpleNamespace(context=context)


@lru_cache(maxsize=1)
def _get_pipeline_graph():
    try:
        from assistant_core.graph import build_llm_graph
    except ModuleNotFoundError:
        return None

    llm = LLMWrapper(model=LLM_MODEL, api_key=GOOGLE_API_KEY)
    return build_llm_graph(
        llm=llm,
        tools=TOOL_FUNCTIONS,
        db=None,
        api_client=None,
    )


def _run_pipeline_sequential(payload: dict[str, Any]) -> dict[str, Any]:
    state = _build_initial_state(payload)
    runtime = _build_runtime()

    for node in (load_user_profile, chat_node):
        state.update(node(state, runtime))

    intent = state.get("intent_classification", {}).get("group", "conversation")
    handler = INTENT_TO_HANDLER.get(intent, conversation_agent)
    state.update(handler(state, runtime))

    while state.get("tool_calls"):
        state.update(execute_tools(state, runtime))
        if state.get("tool_results"):
            state.update(handle_tool_results(state, runtime))
        else:
            break

    state.update(format_output(state, runtime))
    log_interaction(state, runtime)
    return state["final_output"]


def run_pipeline(payload: dict[str, Any]) -> dict[str, Any]:
    graph = _get_pipeline_graph()
    if graph is None:
        return _run_pipeline_sequential(payload)

    state = _build_initial_state(payload)
    final_state = graph.invoke(state)
    return final_state["final_output"]
