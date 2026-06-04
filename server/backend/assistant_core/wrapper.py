from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

import requests

from assistant_core.prompts import (
    CLARIFICATION_RESOLVER_SYSTEM_PROMPT,
    CLARIFICATION_RESOLVER_USER_PROMPT_TEMPLATE,
    CONFIRMATION_RESOLVER_SYSTEM_PROMPT,
    CONFIRMATION_RESOLVER_USER_PROMPT_TEMPLATE,
    GROUP_AGENT_REPAIR_SYSTEM_PROMPT,
    GROUP_AGENT_REPAIR_USER_PROMPT_TEMPLATE,
    GROUP_AGENT_USER_PROMPT_TEMPLATE,
    INFORMATION_VERIFY_SYSTEM_PROMPT,
    INFORMATION_VERIFY_USER_PROMPT_TEMPLATE,
    ROUTER_SYSTEM_PROMPT,
    ROUTER_USER_PROMPT_TEMPLATE,
    TASK_GROUPS,
    TOOL_RESULT_SYSTEM_PROMPT,
    TOOL_RESULT_USER_PROMPT_TEMPLATE,
    get_group_system_prompt,
)
from assistant_core.utils import build_tool_context_string, extract_json_from_response
from config import (
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    OPENROUTER_BASE_URL,
    OPENROUTER_REASONING_ENABLED,
    SMALL_LLM_MODEL,
)

logger = logging.getLogger(__name__)


class OpenRouterChatClient:
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None,
        temperature: float,
        max_output_tokens: int,
    ) -> None:
        self.model = model
        self.api_key = api_key or ""
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens

    def invoke(self, messages: list[Any]):
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")

        content = ""
        if messages:
            first = messages[0]
            content = str(getattr(first, "content", first) or "")

        response = requests.post(
            OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": content}],
                "temperature": self.temperature,
                "max_tokens": self.max_output_tokens,
                "reasoning": {"enabled": bool(OPENROUTER_REASONING_ENABLED)},
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        message = choices[0].get("message", {}) if choices else {}
        return SimpleNamespace(
            content=_normalize_openrouter_content(message.get("content")),
            reasoning_details=message.get("reasoning_details"),
        )


def _normalize_openrouter_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "thinking":
                    continue
                text = item.get("text") or item.get("content")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
            elif isinstance(item, str) and item.strip():
                parts.append(item.strip())
        return "\n".join(parts)
    return "" if content is None else str(content)


def _response_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    content = getattr(response, "content", response)
    return _normalize_openrouter_content(content)


class LLMWrapper:
    def __init__(
        self,
        model: str = "google/gemma-3-4b-it",
        api_key: str | None = None,
        confirmation_model: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ):
        self.model_name = model
        self.temperature = float(LLM_TEMPERATURE if temperature is None else temperature)
        self.max_output_tokens = int(LLM_MAX_TOKENS if max_output_tokens is None else max_output_tokens)
        self.llm = self._build_client(
            model=model,
            api_key=api_key,
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )
        resolved_confirmation_model = confirmation_model or SMALL_LLM_MODEL or model
        self.confirmation_model_name = resolved_confirmation_model
        self.confirmation_temperature = 0.0
        if resolved_confirmation_model == model:
            if self.confirmation_temperature == self.temperature:
                self.confirmation_llm = self.llm
            else:
                self.confirmation_llm = self._build_client(
                    model=resolved_confirmation_model,
                    api_key=api_key,
                    temperature=self.confirmation_temperature,
                    max_output_tokens=self.max_output_tokens,
                )
        else:
            self.confirmation_llm = self._build_client(
                model=resolved_confirmation_model,
                api_key=api_key,
                temperature=self.confirmation_temperature,
                max_output_tokens=self.max_output_tokens,
            )

    def _build_client(
        self,
        *,
        model: str,
        api_key: str | None,
        temperature: float,
        max_output_tokens: int,
    ):
        return OpenRouterChatClient(
            model=model,
            api_key=api_key,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
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
        return llm_client.invoke([SimpleNamespace(content=combined_prompt)])

    def _invoke_with_instruction(self, instruction: str, user_prompt: str):
        return self._invoke_with_client(self.llm, instruction, user_prompt)

    def _invoke_confirmation_with_instruction(self, instruction: str, user_prompt: str):
        return self._invoke_with_client(self.confirmation_llm, instruction, user_prompt)

    def _parse_json_output(self, response_text: Any, fallback: dict[str, Any]) -> dict[str, Any]:
        response_text = _response_text(response_text)
        if not isinstance(response_text, str):
            return fallback
        parsed = extract_json_from_response(response_text)
        if isinstance(parsed, dict):
            return parsed
        return fallback

    def _normalize_tool_plan(self, tool_plan: Any) -> list[dict[str, Any]]:
        if not isinstance(tool_plan, list):
            return []

        normalized_tool_plan = []
        for tool_call in tool_plan:
            if not isinstance(tool_call, dict):
                continue
            name = str(tool_call.get("name") or tool_call.get("tool_name") or "").strip()
            if not name:
                continue
            parameters = tool_call.get("parameters")
            if parameters is None:
                parameters = tool_call.get("args")
            if parameters is None:
                parameters = tool_call.get("params")
            if not isinstance(parameters, dict):
                parameters = {}
            normalized_tool_plan.append({"name": name, "parameters": parameters})
        return normalized_tool_plan

    def _normalize_group_agent_output(
        self,
        parsed: dict[str, Any],
        *,
        raw_response_text: str,
        fallback_subtask: str = "unknown",
    ) -> dict[str, Any]:
        normalized = dict(parsed or {})
        normalized["tool_plan"] = self._normalize_tool_plan(normalized.get("tool_plan", []))
        normalized["dialogue_action"] = str(normalized.get("dialogue_action", "respond_only") or "respond_only")
        normalized["subtask"] = str(normalized.get("subtask", fallback_subtask) or fallback_subtask)
        normalized["assistant_text"] = str(
            normalized.get("assistant_text", raw_response_text if raw_response_text else "") or ""
        )
        normalized["missing_fields"] = (
            normalized.get("missing_fields", [])
            if isinstance(normalized.get("missing_fields"), list)
            else []
        )
        normalized["slots"] = normalized.get("slots", {}) if isinstance(normalized.get("slots"), dict) else {}
        normalized["confidence"] = float(normalized.get("confidence", 0.5) or 0.5)
        return normalized

    def _validate_group_agent_output(
        self,
        *,
        group: str,
        parsed: dict[str, Any],
        tools_available: list[str],
    ) -> list[str]:
        issues: list[str] = []
        dialogue_action = parsed.get("dialogue_action", "respond_only")
        tool_plan = parsed.get("tool_plan", [])
        allowed_tools = set(tools_available)
        valid_actions = {"use_tools", "ask_clarification", "ask_confirmation", "respond_only", "end_conversation"}

        if dialogue_action not in valid_actions:
            issues.append("invalid_dialogue_action")

        if dialogue_action in {"use_tools", "ask_confirmation"} and not tool_plan:
            issues.append("missing_tool_plan")

        if dialogue_action in {"ask_clarification", "respond_only", "end_conversation"} and tool_plan:
            issues.append("unexpected_tool_plan")

        invalid_tool_names = [
            tool_call.get("name")
            for tool_call in tool_plan
            if isinstance(tool_call, dict) and str(tool_call.get("name", "") or "") not in allowed_tools
        ]
        if invalid_tool_names:
            issues.append(f"invalid_tools={','.join(str(name) for name in invalid_tool_names)}")

        if group == "conversation" and tool_plan:
            issues.append("conversation_must_not_call_tools")

        return issues

    def _repair_group_agent_output(
        self,
        *,
        group: str,
        user_input: str,
        current_time: str,
        tools_available: list[str],
        raw_output: str,
    ) -> dict[str, Any]:
        tool_context = build_tool_context_string(tools_available) if tools_available else "(không có tool trực tiếp ở group này)"
        repair_prompt = GROUP_AGENT_REPAIR_USER_PROMPT_TEMPLATE.format(
            group=group,
            current_time=current_time,
            tool_context=tool_context,
            user_input=user_input,
            raw_output=raw_output,
        )
        response = self._invoke_with_instruction(GROUP_AGENT_REPAIR_SYSTEM_PROMPT, repair_prompt)
        return self._parse_json_output(response.content, {})

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

    def _build_compact_tool_results(self, tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        compact_results = []
        for item in tool_results:
            result = item.get("result", {})
            compact_results.append(
                {
                    "tool": item.get("tool"),
                    "parameters": item.get("parameters", {}),
                    "execution_time_ms": item.get("execution_time_ms", 0),
                    "status": result.get("status"),
                    "message": result.get("message"),
                    "answer": result.get("answer"),
                    "formatted_result": result.get("formatted_result"),
                    "query": result.get("query"),
                    "primary_result": result.get("primary_result"),
                    "ambiguity_hint": result.get("ambiguity_hint"),
                    "summary_candidates": result.get("summary_candidates"),
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
        return compact_results

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
        response_text = str(response.content if response.content is not None else "")

        fallback = {
            "assistant_text": response_text,
            "dialogue_action": "respond_only",
            "subtask": "unknown",
            "tool_plan": [],
            "missing_fields": [],
            "slots": {},
            "confidence": 0.5,
        }
        parsed = self._normalize_group_agent_output(
            self._parse_json_output(
                response_text,
                fallback,
            ),
            raw_response_text=response_text,
        )

        validation_issues = self._validate_group_agent_output(
            group=group,
            parsed=parsed,
            tools_available=tools_available,
        )
        if validation_issues:
            logger.warning(
                "Group agent output invalid for group '%s'; attempting repair. Issues=%s Raw=%r",
                group,
                validation_issues,
                response_text,
            )
            try:
                repaired = self._normalize_group_agent_output(
                    self._repair_group_agent_output(
                        group=group,
                        user_input=user_input,
                        current_time=current_time,
                        tools_available=tools_available,
                        raw_output=response_text,
                    ),
                    raw_response_text=response_text,
                )
                repaired_issues = self._validate_group_agent_output(
                    group=group,
                    parsed=repaired,
                    tools_available=tools_available,
                )
                if not repaired_issues:
                    parsed = repaired
                else:
                    logger.warning(
                        "Group agent repair still invalid for group '%s'. Issues=%s",
                        group,
                        repaired_issues,
                    )
            except Exception as exc:
                logger.warning("Group agent repair failed for group '%s': %s", group, exc)

        if self._validate_group_agent_output(group=group, parsed=parsed, tools_available=tools_available):
            parsed = self._normalize_group_agent_output(
                {
                    "assistant_text": (
                        response_text
                        if group == "conversation"
                        else "Mình cần bạn nói rõ thêm để mình thao tác chính xác."
                    ),
                    "dialogue_action": "respond_only" if group == "conversation" else "ask_clarification",
                    "subtask": "chat" if group == "conversation" else "unknown",
                    "tool_plan": [],
                    "missing_fields": [],
                    "slots": {},
                    "confidence": 0.2,
                },
                raw_response_text=response_text,
                fallback_subtask="chat" if group == "conversation" else "unknown",
            )
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
        answer_policy: dict[str, Any] | None,
        tool_results: list[dict[str, Any]],
        response_preferences: str,
        task_summary: str,
        task_transcript: str,
        conversation_summary: str,
        conversation_transcript: str,
        session_mode: str,
    ) -> dict[str, Any]:
        compact_results = self._build_compact_tool_results(tool_results)

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
            answer_policy_json=json.dumps(answer_policy or {}, ensure_ascii=False, indent=2),
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

    def verify_information_result(
        self,
        *,
        user_input: str,
        draft_response: str,
        tool_results: list[dict[str, Any]],
        response_preferences: str,
        task_summary: str,
        task_transcript: str,
        conversation_summary: str,
        conversation_transcript: str,
        session_mode: str,
        current_time: str,
    ) -> dict[str, Any]:
        compact_results = self._build_compact_tool_results(tool_results)
        user_prompt = INFORMATION_VERIFY_USER_PROMPT_TEMPLATE.format(
            session_mode=session_mode,
            current_time=current_time,
            response_preferences=response_preferences,
            task_summary=task_summary,
            task_transcript=task_transcript,
            conversation_summary=conversation_summary,
            conversation_transcript=conversation_transcript,
            user_input=user_input,
            draft_response=draft_response or "",
            tool_results_json=json.dumps(compact_results, ensure_ascii=False, indent=2),
        )
        try:
            response = self._invoke_confirmation_with_instruction(INFORMATION_VERIFY_SYSTEM_PROMPT, user_prompt)
        except Exception as exc:
            if self.confirmation_llm is self.llm:
                raise
            logger.warning(
                "Information verifier model '%s' failed; falling back to main model '%s': %s",
                self.confirmation_model_name,
                self.model_name,
                exc,
            )
            response = self._invoke_with_instruction(INFORMATION_VERIFY_SYSTEM_PROMPT, user_prompt)

        parsed = self._parse_json_output(
            response.content,
            {
                "decision": "answer",
                "assistant_text": "",
                "reason": "fallback",
                "confidence": 0.4,
                "missing_fields": [],
                "refined_query": "",
                "answer_style": "balanced",
                "follow_up_mode": "none",
                "should_strip_follow_up_offer": True,
                "answer_outline": [],
            },
        )
        decision = str(parsed.get("decision", "answer") or "answer")
        if decision not in {"answer", "clarify", "refine_search"}:
            decision = "answer"
        answer_style = str(parsed.get("answer_style", "balanced") or "balanced")
        if answer_style not in {"concise", "balanced", "detailed"}:
            answer_style = "balanced"
        follow_up_mode = str(parsed.get("follow_up_mode", "none") or "none")
        if follow_up_mode not in {"none", "clarify"}:
            follow_up_mode = "none"
        return {
            "decision": decision,
            "assistant_text": str(parsed.get("assistant_text", "") or ""),
            "reason": str(parsed.get("reason", "") or ""),
            "confidence": float(parsed.get("confidence", 0.5) or 0.5),
            "missing_fields": parsed.get("missing_fields", []) if isinstance(parsed.get("missing_fields"), list) else [],
            "refined_query": str(parsed.get("refined_query", "") or ""),
            "answer_style": answer_style,
            "follow_up_mode": follow_up_mode,
            "should_strip_follow_up_offer": bool(parsed.get("should_strip_follow_up_offer", True)),
            "answer_outline": parsed.get("answer_outline", []) if isinstance(parsed.get("answer_outline"), list) else [],
        }

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

    def resolve_clarification_reply(
        self,
        *,
        group: str,
        subtask: str,
        pending_question: str,
        original_user_input: str,
        user_reply: str,
        response_preferences: str,
        task_summary: str,
        task_transcript: str,
        conversation_summary: str,
        conversation_transcript: str,
        session_mode: str,
    ) -> dict[str, Any]:
        user_prompt = CLARIFICATION_RESOLVER_USER_PROMPT_TEMPLATE.format(
            group=group,
            subtask=subtask,
            session_mode=session_mode,
            response_preferences=response_preferences,
            pending_question=pending_question,
            original_user_input=original_user_input,
            task_summary=task_summary,
            task_transcript=task_transcript,
            conversation_summary=conversation_summary,
            conversation_transcript=conversation_transcript,
            user_reply=user_reply,
        )
        try:
            response = self._invoke_confirmation_with_instruction(CLARIFICATION_RESOLVER_SYSTEM_PROMPT, user_prompt)
        except Exception as exc:
            if self.confirmation_llm is self.llm:
                raise
            logger.warning(
                "Clarification model '%s' failed; falling back to main model '%s': %s",
                self.confirmation_model_name,
                self.model_name,
                exc,
            )
            response = self._invoke_with_instruction(CLARIFICATION_RESOLVER_SYSTEM_PROMPT, user_prompt)
        parsed = self._parse_json_output(
            response.content,
            {
                "decision": "unclear",
                "assistant_text": "Mình cần bạn nói rõ hơn một chút để mình hiểu đúng ý.",
                "rewritten_user_input": "",
                "reason": "fallback",
                "confidence": 0.2,
            },
        )
        decision = str(parsed.get("decision", "unclear") or "unclear")
        if decision not in {"resolved", "unclear", "cancel"}:
            decision = "unclear"

        return {
            "decision": decision,
            "assistant_text": str(parsed.get("assistant_text", "") or ""),
            "rewritten_user_input": str(parsed.get("rewritten_user_input", "") or ""),
            "reason": str(parsed.get("reason", "") or ""),
            "confidence": float(parsed.get("confidence", 0.5) or 0.5),
        }
