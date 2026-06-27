from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from typing import Any

from assistant_core.nodes import load_user_profile
from assistant_core.prompts import TASK_GROUPS
from assistant_core.utils import build_response_preferences_text, format_memory, format_user_profile, get_current_time_string
from assistant_core.wrapper import LLMWrapper
from assistant_tools.registry import TOOL_FUNCTIONS, execute_tool
from config import LLM_MODEL, OPENROUTER_API_KEY
from logging_utils import log_kv


logger = logging.getLogger(__name__)


def _build_runtime() -> SimpleNamespace:
    llm = LLMWrapper(model=LLM_MODEL, api_key=OPENROUTER_API_KEY)
    return SimpleNamespace(context=SimpleNamespace(llm=llm, tools=TOOL_FUNCTIONS, db=None, api_client=None))


def _build_initial_state(payload: dict[str, Any]) -> dict[str, Any]:
    text_input = str(payload.get("text_input") or payload.get("stt_text") or "").strip()
    return {
        "user_id": str(payload.get("user_id") or "").strip(),
        "nfc_tag_id": str(payload.get("nfc_tag_id") or "").strip(),
        "text_input": text_input,
        "current_time": payload.get("current_time") or get_current_time_string(),
        "session_state": {},
    }


def _tool_result_to_command(tool_name: str, result: dict[str, Any]) -> dict[str, Any] | None:
    payload = result.get("device_payload")
    if isinstance(payload, dict) and payload:
        return dict(payload)
    if tool_name == "youtube_stream":
        stream_info = result.get("stream_info")
        if isinstance(stream_info, dict):
            payload = stream_info.get("device_payload")
            if isinstance(payload, dict) and payload:
                return dict(payload)
    return None


def _tool_result_to_stream_tool(tool_name: str, result: dict[str, Any]) -> dict[str, Any] | None:
    if tool_name != "youtube_search":
        return None
    primary_result = result.get("primary_result")
    if not isinstance(primary_result, dict):
        return None
    video_id = str(primary_result.get("video_id") or "").strip()
    if not video_id:
        return None
    query = str(result.get("query") or "").strip()
    mode = "video" if str(primary_result.get("is_live") or "").lower() == "true" else "audio"
    return {
        "name": "youtube_stream",
        "parameters": {
            "video_id": video_id,
            "query": query,
            "mode": mode,
        },
    }


def _build_tool_outputs(tool_calls: list[dict[str, Any]], *, nfc_tag_id: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tool_outputs: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []

    for tool_call in tool_calls:
        tool_name = str(tool_call.get("name") or "").strip()
        parameters = tool_call.get("parameters") if isinstance(tool_call.get("parameters"), dict) else {}
        if not tool_name:
            continue
        started = time.time()
        result = execute_tool(tool_name, parameters, nfc_tag_id=nfc_tag_id)
        elapsed_ms = int((time.time() - started) * 1000)
        tool_outputs.append(
            {
                "tool": tool_name,
                "parameters": parameters,
                "execution_time_ms": elapsed_ms,
                "result": result,
            }
        )
        command = _tool_result_to_command(tool_name, result)
        if command:
            commands.append(command)
    return tool_outputs, commands


def _build_final_output(
    *,
    state: dict[str, Any],
    route: dict[str, Any],
    assistant_text: str,
    status: str,
    tool_outputs: list[dict[str, Any]],
    commands: list[dict[str, Any]],
    metadata: dict[str, Any],
    user_profile: dict[str, Any],
) -> dict[str, Any]:
    tts_text = assistant_text.strip()
    expect_user_input = status in {"needs_clarification", "needs_confirmation"}
    final_output = {
        "tts_text": tts_text,
        "status": status,
        "route": route,
        "dialog": {
            "mode": "single_turn",
            "expect_user_input": expect_user_input,
            "pending_kind": None,
            "pending_question": None,
        },
        "session_state": {},
        "actions": [],
        "tool_outputs": tool_outputs,
        "commands": commands,
        "edge_payload": {
            "version": 2,
            "commands": commands,
        },
        "metadata": {
            "intent": metadata.get("intent", metadata.get("group", "conversation")),
            "group": metadata.get("group", "conversation"),
            "subtask": metadata.get("subtask", "chat"),
            "confidence": metadata.get("confidence", 0.8),
            "task_status": status,
            "timestamp": state.get("current_time"),
            "user_id": state.get("user_id", ""),
            "nfc_tag_id": state.get("nfc_tag_id", ""),
            "total_latency_ms": metadata.get("total_latency_ms", 0),
            "tool_count": len(tool_outputs),
            "edge_command_count": len(commands),
        },
        "user_profile": user_profile,
    }
    return final_output


def _summarize_tools(tool_outputs: list[dict[str, Any]]) -> str:
    if not tool_outputs:
        return ""
    parts = []
    for item in tool_outputs:
        result = item.get("result", {})
        message = str(result.get("message") or result.get("answer") or result.get("formatted_result") or "").strip()
        if message:
            parts.append(message)
    return "\n".join(parts).strip()


def run_pipeline(payload: dict[str, Any]) -> dict[str, Any]:
    request = _build_initial_state(payload)
    runtime = _build_runtime()
    llm: LLMWrapper = runtime.context.llm
    start_time = time.time()

    profile_state = load_user_profile(request, runtime)
    user_profile = profile_state.get("user_profile", {}) if isinstance(profile_state, dict) else {}
    user_name = profile_state.get("user_name", "Guest") if isinstance(profile_state, dict) else "Guest"
    user_memory = profile_state.get("user_memory", []) if isinstance(profile_state, dict) else []
    response_preferences = build_response_preferences_text(user_profile if isinstance(user_profile, dict) else {})
    user_profile_text = format_user_profile(user_profile if isinstance(user_profile, dict) else {})
    memory_text = format_memory(user_memory if isinstance(user_memory, list) else [])
    system_prompt_context = (
        "Single-turn voice assistant. "
        "If the request is ambiguous or incomplete, do not guess. "
        "Return a short guidance message with an example. "
        "Do not keep pending state across turns."
    )

    route = llm.route_intent(
        user_input=request["text_input"],
        conversation_summary="",
        conversation_transcript="",
        session_mode="single_turn",
        pending_summary="",
        system_prompt_context=system_prompt_context,
        memory_context=memory_text,
        preferences_context=response_preferences,
    )
    group = route.get("group", "conversation")
    if group not in TASK_GROUPS:
        group = "conversation"

    log_kv(
        logger,
        logging.INFO,
        "assistant_single_turn_route",
        user_input=request["text_input"],
        route_group=group,
        confidence=route.get("confidence", 0.5),
        reason=route.get("reason", ""),
    )

    task_result = llm.run_group_agent(
        group=group,
        user_input=request["text_input"],
        user_name=user_name,
        current_time=request["current_time"],
        response_preferences=response_preferences,
        user_profile=user_profile_text,
        task_summary="",
        task_transcript="",
        conversation_summary="",
        conversation_transcript="",
        tools_available=list(TASK_GROUPS.get(group, {}).get("tools", [])),
        session_mode="single_turn",
        return_mode="conversation",
        pending_summary="",
        system_prompt_context=system_prompt_context,
        memory_context=memory_text,
        preferences_context=response_preferences,
    )

    assistant_text = str(task_result.get("assistant_text") or "").strip()
    dialogue_action = str(task_result.get("dialogue_action") or "respond_only").strip()
    tool_plan = task_result.get("tool_plan", []) if isinstance(task_result.get("tool_plan"), list) else []
    missing_fields = task_result.get("missing_fields", []) if isinstance(task_result.get("missing_fields"), list) else []

    tool_outputs: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []
    if dialogue_action in {"use_tools", "ask_confirmation"} and tool_plan:
        tool_outputs, commands = _build_tool_outputs(tool_plan[:3], nfc_tag_id=request.get("nfc_tag_id") or None)
        if group == "media" and tool_outputs:
            first_media_tool = tool_outputs[0] if tool_outputs and isinstance(tool_outputs[0], dict) else {}
            if first_media_tool.get("tool") == "youtube_search":
                search_result = first_media_tool.get("result") if isinstance(first_media_tool.get("result"), dict) else {}
                search_items = search_result.get("results", []) if isinstance(search_result.get("results"), list) else []
                media_choice = llm.select_media_search_result(
                    user_input=request["text_input"],
                    query=str(search_result.get("query") or request["text_input"] or "").strip(),
                    mode=str(task_result.get("slots", {}).get("mode") or "audio"),
                    search_results=search_items,
                    response_preferences=response_preferences,
                    task_summary="",
                    task_transcript="",
                    conversation_summary="",
                    conversation_transcript="",
                    session_mode="single_turn",
                )
                if media_choice.get("decision") == "clarify" or not media_choice.get("selected_video_id"):
                    assistant_text = str(media_choice.get("assistant_text") or assistant_text).strip() or "Mình chưa tìm được nội dung đủ rõ để phát."
                    dialogue_action = "ask_clarification"
                    tool_outputs = tool_outputs[:1]
                    commands = commands[:1]
                else:
                    stream_tool = {
                        "name": "youtube_stream",
                        "parameters": {
                            "video_id": media_choice.get("selected_video_id"),
                            "query": str(search_result.get("query") or request["text_input"] or "").strip(),
                            "mode": media_choice.get("selected_mode") or "audio",
                        },
                    }
                    stream_started = time.time()
                    stream_result = execute_tool(
                        stream_tool["name"],
                        stream_tool["parameters"],
                        nfc_tag_id=request.get("nfc_tag_id") or None,
                    )
                    stream_elapsed_ms = int((time.time() - stream_started) * 1000)
                    tool_outputs.append(
                        {
                            "tool": stream_tool["name"],
                            "parameters": stream_tool["parameters"],
                            "execution_time_ms": stream_elapsed_ms,
                            "result": stream_result,
                        }
                    )
                    stream_command = _tool_result_to_command(stream_tool["name"], stream_result)
                    if stream_command:
                        commands.append(stream_command)
                    if stream_result.get("status") == "success":
                        commands = [command for command in commands if command.get("type") != "youtube_search_results"]
                        assistant_text = str(stream_result.get("message") or assistant_text).strip() or assistant_text
                    else:
                        assistant_text = str(stream_result.get("message") or assistant_text).strip() or assistant_text
        if tool_outputs:
            synthesized = llm.synthesize_tool_results(
                group=group,
                user_input=request["text_input"],
                draft_response=assistant_text,
                answer_policy=None,
                tool_results=tool_outputs,
                response_preferences=response_preferences,
                task_summary="",
                task_transcript="",
                conversation_summary="",
                conversation_transcript="",
                session_mode="single_turn",
                system_prompt_context=system_prompt_context,
                memory_context=memory_text,
                preferences_context=response_preferences,
            )
            assistant_text = str(synthesized.get("assistant_text") or assistant_text).strip()
            dialogue_action = str(synthesized.get("dialogue_action") or dialogue_action).strip()

    if not assistant_text:
        assistant_text = "Mình chưa rõ ý bạn. Bạn nói rõ hơn giúp mình nhé, ví dụ: thêm sữa vào danh sách mua sắm."

    if dialogue_action == "ask_clarification" or missing_fields:
        status = "needs_clarification"
    elif dialogue_action == "ask_confirmation":
        status = "needs_confirmation"
    elif tool_outputs:
        status = "completed"
    else:
        status = "completed"

    elapsed_ms = int((time.time() - start_time) * 1000)
    metadata = {
        "group": group,
        "intent": route.get("group", group),
        "confidence": route.get("confidence", 0.5),
        "subtask": task_result.get("subtask", "chat"),
        "total_latency_ms": elapsed_ms,
    }
    final_output = _build_final_output(
        state=request,
        route={
            "group": group,
            "subtask": task_result.get("subtask", "chat"),
            "return_mode": "conversation",
            "mode": "single_turn",
        },
        assistant_text=assistant_text,
        status=status,
        tool_outputs=tool_outputs,
        commands=commands,
        metadata=metadata,
        user_profile=user_profile if isinstance(user_profile, dict) else {},
    )
    final_output["context"] = {
        "user_name": user_name,
        "user_memory": user_memory,
        "response_preferences": response_preferences,
    }
    final_output["debug"] = {
        "route_group": group,
        "dialogue_action": dialogue_action,
        "tool_plan_count": len(tool_plan),
        "tool_summary": _summarize_tools(tool_outputs),
    }
    return final_output
