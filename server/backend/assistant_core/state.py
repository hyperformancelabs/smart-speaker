from dataclasses import dataclass
from typing import Any

from typing_extensions import TypedDict

try:
    from langgraph.graph import MessagesState as _LangGraphMessagesState
except Exception:
    class _LangGraphMessagesState(TypedDict, total=False):
        messages: list[dict[str, Any]]


class LLMState(_LangGraphMessagesState, total=False):
    user_id: str
    nfc_tag_id: str
    text_input: str
    task_input: str
    user_profile: dict[str, Any]
    user_memory: list[str]
    user_name: str
    current_time: str
    conversation_history: str
    session_state: dict[str, Any]
    intent_classification: dict[str, Any]
    route_group: str
    route_return_mode: str
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    executed_actions: list[dict[str, Any]]
    response_text: str
    metadata: dict[str, Any]
    final_output: dict[str, Any]
    task_status: str
    dialogue_action: str
    processing_latency_ms: int
    needs_clarification: bool
    clarification_prompt: str
    missing_fields: list[str]
    clarification_count: int


@dataclass
class LLMContext:
    """
    Runtime context passed to nodes
    """

    llm: Any
    tools: dict[str, Any]
    db: Any
    api_client: Any
    request_id: str = ""
    timestamp: str = ""
