from __future__ import annotations

import json
import logging
from typing import Any

try:
    from langchain_core.messages import HumanMessage
except ModuleNotFoundError:
    class HumanMessage:  # type: ignore[override]
        def __init__(self, content: str):
            self.content = content


try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except ModuleNotFoundError:
    class ChatGoogleGenerativeAI:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, *args, **kwargs):
            raise RuntimeError("langchain_google_genai is not installed in this environment")

from assistant_core.prompts import (
    CONFIRMATION_RESOLVER_SYSTEM_PROMPT,
    CONFIRMATION_RESOLVER_USER_PROMPT_TEMPLATE,
    GROUP_AGENT_USER_PROMPT_TEMPLATE,
    ROUTER_SYSTEM_PROMPT,
    ROUTER_USER_PROMPT_TEMPLATE,
    TASK_GROUPS,
    TOOL_RESULT_SYSTEM_PROMPT,
    TOOL_RESULT_USER_PROMPT_TEMPLATE,
    get_group_system_prompt,
)
from assistant_core.utils import build_tool_context_string, extract_json_from_response
from config import SMALL_LLM_MODEL

logger = logging.getLogger(__name__)


class LLMWrapper:
    def __init__(
        self,
        model: str = "gemma-3-4b-it",
        api_key: str | None = None,
        confirmation_model: str | None = None,
    ):
        self.model_name = model
        self.llm = self._build_client(model=model, api_key=api_key)
        resolved_confirmation_model = confirmation_model or SMALL_LLM_MODEL or model
        self.confirmation_model_name = resolved_confirmation_model
        if resolved_confirmation_model == model:
            self.confirmation_llm = self.llm
        else:
            self.confirmation_llm = self._build_client(model=resolved_confirmation_model, api_key=api_key)

    def _build_client(self, *, model: str, api_key: str | None):
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=0.7,
            max_output_tokens=1024,
        )

    def _build_combined_prompt(self, instruction: str, user_prompt: str) -> str:
        return (
            "Huong dan he thong:\n"
            f"{instruction.strip()}\n\n"
            "Yeu cau nguoi dung:\n"
            f"{user_prompt.strip()}"
        )

    def _invoke_with_client(self, llm_client, instruction: str, user_prompt: str):
        combined_prompt = self._build_combined_prompt(instruction, user_prompt)
        return llm_client.invoke([HumanMessage(content=combined_prompt)])

    def _invoke_with_instruction(self, instruction: str, user_prompt: str):
        return self._invoke_with_client(self.llm, instruction, user_prompt)

    def _invoke_confirmation_with_instruction(self, instruction: str, user_prompt: str):
        return self._invoke_with_client(self.confirmation_llm, instruction, user_prompt)

    def _parse_json_output(self, response_text: Any, fallback: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(response_text, str):
            return fallback
        parsed = extract_json_from_response(response_text)
        if isinstance(parsed, dict):
            return parsed
        return fallback

    def route_intent(
        self,
        *,
        user_input: str,
        conversation_summary: str,
        conversation_transcript: str,
        session_mode: str,
        pending_summary: str,
    ) -> dict[str, Any]:
        prompt = ROUTER_USER_PROMPT_TEMPLATE.format(
            user_input=user_input,
            conversation_summary=conversation_summary,
            conversation_transcript=conversation_transcript,
            session_mode=session_mode,
            pending_summary=pending_summary,
        )
        response = self._invoke_with_instruction(ROUTER_SYSTEM_PROMPT, prompt)
        response_text = response.content
        route_data = self._parse_json_output(
            response_text,
            {"group": "conversation", "confidence": 0.5, "reason": "fallback"},
        )

        group = route_data.get("group")
        if group not in TASK_GROUPS:
            group = "conversation"

        return {
            "group": group,
            "confidence": float(route_data.get("confidence", 0.5) or 0.5),
            "reason": str(route_data.get("reason", "") or ""),
        }

    def run_group_agent(
        self,
        *,
        group: str,
        user_input: str,
        user_name: str,
        current_time: str,
        response_preferences: str,
        user_profile: str,
        task_summary: str,
        task_transcript: str,
        conversation_summary: str,
        conversation_transcript: str,
        tools_available: list[str],
        session_mode: str,
        return_mode: str,
        pending_summary: str,
    ) -> dict[str, Any]:
        tool_context = build_tool_context_string(tools_available) if tools_available else "(không có tool trực tiếp ở group này)"
        system_prompt = get_group_system_prompt(group)
        user_prompt = GROUP_AGENT_USER_PROMPT_TEMPLATE.format(
            group=group,
            session_mode=session_mode,
            return_mode=return_mode,
            pending_summary=pending_summary,
            current_time=current_time,
            user_name=user_name,
            response_preferences=response_preferences,
            user_profile=user_profile,
            task_summary=task_summary,
            task_transcript=task_transcript,
            conversation_summary=conversation_summary,
            conversation_transcript=conversation_transcript,
            tool_context=tool_context,
            user_input=user_input,
        )
        response = self._invoke_with_instruction(system_prompt, user_prompt)
        response_text = response.content

        parsed = self._parse_json_output(
            response_text,
            {
                "assistant_text": response_text,
                "dialogue_action": "respond_only",
                "subtask": "unknown",
                "tool_plan": [],
                "missing_fields": [],
                "slots": {},
                "confidence": 0.5,
            },
        )

        tool_plan = parsed.get("tool_plan", [])
        if not isinstance(tool_plan, list):
            tool_plan = []

        normalized_tool_plan = []
        for tool_call in tool_plan:
            if not isinstance(tool_call, dict):
                continue
            name = tool_call.get("name")
            if not name:
                continue
            parameters = tool_call.get("parameters", {})
            if not isinstance(parameters, dict):
                parameters = {}
            normalized_tool_plan.append({"name": name, "parameters": parameters})

        parsed["tool_plan"] = normalized_tool_plan
        parsed["dialogue_action"] = str(parsed.get("dialogue_action", "respond_only") or "respond_only")
        parsed["subtask"] = str(parsed.get("subtask", "unknown") or "unknown")
        parsed["assistant_text"] = str(parsed.get("assistant_text", "") or "")
        parsed["missing_fields"] = parsed.get("missing_fields", []) if isinstance(parsed.get("missing_fields"), list) else []
        parsed["slots"] = parsed.get("slots", {}) if isinstance(parsed.get("slots"), dict) else {}
        parsed["confidence"] = float(parsed.get("confidence", 0.5) or 0.5)
        return parsed

    def specialist_agent(self, **kwargs) -> dict[str, Any]:
        return self.run_group_agent(**kwargs)

    def free_conversation(self, **kwargs) -> dict[str, Any]:
        return self.run_group_agent(group="conversation", **kwargs)

    def synthesize_tool_results(
        self,
        *,
        group: str,
        user_input: str,
        draft_response: str,
        tool_results: list[dict[str, Any]],
        response_preferences: str,
        task_summary: str,
        task_transcript: str,
        conversation_summary: str,
        conversation_transcript: str,
        session_mode: str,
    ) -> dict[str, Any]:
        compact_results = []
        for item in tool_results:
            result = item.get("result", {})
            compact_results.append(
                {
                    "tool": item.get("tool"),
                    "status": result.get("status"),
                    "message": result.get("message"),
                    "answer": result.get("answer"),
                    "formatted_result": result.get("formatted_result"),
                    "query": result.get("query"),
                    "primary_result": result.get("primary_result"),
                    "ambiguity_hint": result.get("ambiguity_hint"),
                    "device_payload": result.get("device_payload"),
                    "results": result.get("results"),
                    "content_items": result.get("content_items"),
                    "details": {
                        key: value
                        for key, value in result.items()
                        if key
                        not in {
                            "results",
                            "content_items",
                            "llm_documents",
                            "summary_candidates",
                            "device_payload",
                            "stream_info",
                        }
                    },
                }
            )

        user_prompt = TOOL_RESULT_USER_PROMPT_TEMPLATE.format(
            group=group,
            session_mode=session_mode,
            response_preferences=response_preferences,
            task_summary=task_summary,
            task_transcript=task_transcript,
            conversation_summary=conversation_summary,
            conversation_transcript=conversation_transcript,
            user_input=user_input,
            draft_response=draft_response or "",
            tool_results_json=json.dumps(compact_results, ensure_ascii=False, indent=2),
        )
        response = self._invoke_with_instruction(TOOL_RESULT_SYSTEM_PROMPT, user_prompt)
        response_text = response.content
        parsed = self._parse_json_output(
            response_text,
            {
                "assistant_text": response_text,
                "dialogue_action": "respond_only",
                "missing_fields": [],
                "confidence": 0.5,
            },
        )
        parsed["assistant_text"] = str(parsed.get("assistant_text", "") or "")
        parsed["dialogue_action"] = str(parsed.get("dialogue_action", "respond_only") or "respond_only")
        parsed["missing_fields"] = parsed.get("missing_fields", []) if isinstance(parsed.get("missing_fields"), list) else []
        parsed["confidence"] = float(parsed.get("confidence", 0.5) or 0.5)
        return parsed

    def resolve_confirmation_reply(
        self,
        *,
        group: str,
        subtask: str,
        pending_question: str,
        original_user_input: str,
        tool_plan: list[dict[str, Any]],
        user_reply: str,
        response_preferences: str,
        task_summary: str,
        task_transcript: str,
        conversation_summary: str,
        conversation_transcript: str,
        session_mode: str,
    ) -> dict[str, Any]:
        user_prompt = CONFIRMATION_RESOLVER_USER_PROMPT_TEMPLATE.format(
            group=group,
            subtask=subtask,
            session_mode=session_mode,
            response_preferences=response_preferences,
            pending_question=pending_question,
            original_user_input=original_user_input,
            tool_plan_json=json.dumps(tool_plan, ensure_ascii=False, indent=2),
            task_summary=task_summary,
            task_transcript=task_transcript,
            conversation_summary=conversation_summary,
            conversation_transcript=conversation_transcript,
            user_reply=user_reply,
        )
        try:
            response = self._invoke_confirmation_with_instruction(CONFIRMATION_RESOLVER_SYSTEM_PROMPT, user_prompt)
        except Exception as exc:
            if self.confirmation_llm is self.llm:
                raise
            logger.warning(
                "Confirmation model '%s' failed; falling back to main model '%s': %s",
                self.confirmation_model_name,
                self.model_name,
                exc,
            )
            response = self._invoke_with_instruction(CONFIRMATION_RESOLVER_SYSTEM_PROMPT, user_prompt)
        response_text = response.content
        parsed = self._parse_json_output(
            response_text,
            {
                "decision": "unclear",
                "assistant_text": "Mình cần bạn xác nhận là đồng ý, hủy, hoặc nói rõ muốn chỉnh gì.",
                "rewritten_user_input": "",
                "reason": "fallback",
                "confidence": 0.2,
            },
        )
        decision = str(parsed.get("decision", "unclear") or "unclear")
        if decision not in {"confirm", "deny", "revise", "unclear"}:
            decision = "unclear"

        return {
            "decision": decision,
            "assistant_text": str(parsed.get("assistant_text", "") or ""),
            "rewritten_user_input": str(parsed.get("rewritten_user_input", "") or ""),
            "reason": str(parsed.get("reason", "") or ""),
            "confidence": float(parsed.get("confidence", 0.5) or 0.5),
        }
