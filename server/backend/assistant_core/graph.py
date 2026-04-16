from __future__ import annotations

from types import SimpleNamespace

from langgraph.graph import END, START, StateGraph

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
    route_after_handle_tool_results,
    route_after_task_agent,
    route_after_tools,
)
from assistant_core.state import LLMContext, LLMState


INTENT_TO_NODE = {
    "media": "media_agent",
    "information_query": "information_query_agent",
    "personalization": "personalization_agent",
    "productivity": "productivity_agent",
    "conversation": "conversation_agent",
}


def _route_after_router(state: LLMState) -> str:
    intent = state.get("intent_classification", {}).get("group", "conversation")
    return intent if intent in INTENT_TO_NODE else "conversation"


def build_llm_graph(llm, tools, db, api_client):
    """
    Build the chat-first LangGraph workflow for the assistant.
    """
    runtime = SimpleNamespace(
        context=LLMContext(
            llm=llm,
            tools=tools,
            db=db,
            api_client=api_client,
        )
    )

    def bind(node_fn):
        return lambda state: node_fn(state, runtime)

    builder = StateGraph(LLMState)

    builder.add_node("load_user_profile", bind(load_user_profile))
    builder.add_node("chat_node", bind(chat_node))
    builder.add_node("media_agent", bind(media_agent))
    builder.add_node("information_query_agent", bind(information_query_agent))
    builder.add_node("personalization_agent", bind(personalization_agent))
    builder.add_node("productivity_agent", bind(productivity_agent))
    builder.add_node("conversation_agent", bind(conversation_agent))
    builder.add_node("execute_tools", bind(execute_tools))
    builder.add_node("handle_tool_results", bind(handle_tool_results))
    builder.add_node("format_output", bind(format_output))
    builder.add_node("log_interaction", bind(log_interaction))

    builder.add_edge(START, "load_user_profile")
    builder.add_edge("load_user_profile", "chat_node")
    builder.add_conditional_edges(
        "chat_node",
        _route_after_router,
        INTENT_TO_NODE,
    )

    for task_node in INTENT_TO_NODE.values():
        builder.add_conditional_edges(
            task_node,
            route_after_task_agent,
            {
                "execute_tools": "execute_tools",
                "format_output": "format_output",
            },
        )

    builder.add_conditional_edges(
        "execute_tools",
        route_after_tools,
        {
            "handle_tool_results": "handle_tool_results",
            "format_output": "format_output",
        },
    )
    builder.add_conditional_edges(
        "handle_tool_results",
        route_after_handle_tool_results,
        {
            "execute_tools": "execute_tools",
            "format_output": "format_output",
        },
    )
    builder.add_edge("format_output", "log_interaction")
    builder.add_edge("log_interaction", END)

    return builder.compile()
