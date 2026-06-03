from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


SERVER_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_BACKEND_ROOT))

from assistant_core import nodes
from assistant_core.wrapper import LLMWrapper
from assistant_tools import backend_tools
from assistant_tools import common as tool_common


class FakePlannerLLM:
    def __init__(
        self,
        planner_result: dict[str, object] | None = None,
        synthesis_result: dict[str, object] | None = None,
        clarification_result: dict[str, object] | None = None,
    ):
        self.planner_result = planner_result or {}
        self.synthesis_result = synthesis_result or {}
        self.clarification_result = clarification_result or {}
        self.group_agent_calls: list[dict[str, object]] = []
        self.synthesis_calls: list[dict[str, object]] = []
        self.clarification_calls: list[dict[str, object]] = []

    def run_group_agent(self, **kwargs):
        self.group_agent_calls.append(kwargs)
        return self.planner_result

    def synthesize_tool_results(self, **kwargs):
        self.synthesis_calls.append(kwargs)
        return self.synthesis_result

    def resolve_clarification_reply(self, **kwargs):
        self.clarification_calls.append(kwargs)
        return self.clarification_result


class ProductivityRoutingTests(unittest.TestCase):
    def test_clean_media_query_removes_common_command_fillers(self) -> None:
        self.assertEqual(nodes._clean_media_query("Hãy mở bài lạc trôi của Sơn Tùng"), "lac troi son tung")

    def test_productivity_agent_uses_llm_tool_plan_for_todo_list(self) -> None:
        llm = FakePlannerLLM(
            planner_result={
                "assistant_text": "Mình tạo danh sách cho bạn ngay.",
                "dialogue_action": "use_tools",
                "subtask": "list.create",
                "tool_plan": [{"name": "create_list", "parameters": {"list_name": "todo"}}],
                "missing_fields": [],
                "slots": {"list_name": "todo"},
                "confidence": 0.98,
            }
        )
        result = nodes.productivity_agent(
            {
                "text_input": "tạo to-do list",
                "session_state": {"mode": "conversation"},
                "route_return_mode": "conversation",
            },
            runtime=SimpleNamespace(context=SimpleNamespace(llm=llm)),
        )

        self.assertEqual(result["dialogue_action"], "use_tools")
        self.assertEqual(result["metadata"]["subtask"], "list.create")
        self.assertEqual(
            result["tool_calls"],
            [{"name": "create_list", "parameters": {"list_name": "todo"}}],
        )
        self.assertEqual(
            llm.group_agent_calls[0]["tools_available"],
            nodes.TASK_GROUPS["productivity"]["tools"],
        )

    def test_productivity_agent_uses_llm_clarification_instead_of_direct_rules(self) -> None:
        llm = FakePlannerLLM(
            planner_result={
                "assistant_text": "Bạn muốn đặt báo thức lúc mấy giờ?",
                "dialogue_action": "ask_clarification",
                "subtask": "alarm.create",
                "tool_plan": [],
                "missing_fields": ["time"],
                "slots": {},
                "confidence": 0.72,
            }
        )
        result = nodes.productivity_agent(
            {
                "text_input": "đặt báo thức",
                "session_state": {"mode": "conversation"},
                "route_return_mode": "conversation",
            },
            runtime=SimpleNamespace(context=SimpleNamespace(llm=llm)),
        )

        self.assertEqual(result["dialogue_action"], "ask_clarification")
        self.assertEqual(result["metadata"]["subtask"], "alarm.create")
        self.assertEqual(result["session_state"]["active_task"]["pending"]["missing_fields"], ["time"])

    def test_productivity_tool_success_uses_llm_synthesis(self) -> None:
        llm = FakePlannerLLM(
            synthesis_result={
                "assistant_text": "Mình đã tạo danh sách todo rồi.",
                "dialogue_action": "respond_only",
                "missing_fields": [],
                "confidence": 0.91,
            }
        )
        result = nodes.handle_tool_results(
            {
                "route_group": "productivity",
                "route_return_mode": "conversation",
                "session_state": {"mode": "conversation"},
                "metadata": {"group": "productivity", "subtask": "list.create", "confidence": 0.9},
                "tool_results": [
                    {
                        "tool": "create_list",
                        "result": {"status": "success", "list_name": "todo"},
                        }
                ],
            },
            runtime=SimpleNamespace(context=SimpleNamespace(llm=llm)),
        )

        self.assertEqual(result["response_text"], "Mình đã tạo danh sách todo rồi.")
        self.assertEqual(result["dialogue_action"], "respond_only")
        self.assertEqual(result["metadata"]["task_status"], "completed")
        self.assertEqual(len(llm.synthesis_calls), 1)

    def test_productivity_tool_failure_uses_llm_synthesis_instead_of_raw_error(self) -> None:
        llm = FakePlannerLLM(
            synthesis_result={
                "assistant_text": "Mình chưa đặt được báo thức. Bạn nói rõ ngày và giờ giúp mình nhé.",
                "dialogue_action": "ask_clarification",
                "missing_fields": ["scheduled_for"],
                "confidence": 0.89,
            }
        )
        result = nodes.handle_tool_results(
            {
                "route_group": "productivity",
                "route_return_mode": "conversation",
                "session_state": {"mode": "conversation"},
                "response_text": "Mình đặt báo thức cho bạn ngay.",
                "metadata": {"group": "productivity", "subtask": "alarm.create", "confidence": 0.9},
                "tool_results": [
                    {
                        "tool": "create_alarm",
                        "parameters": {"schedule_type": "datetime", "scheduled_for": "bad-value"},
                        "result": {
                            "status": "error",
                            "message": "Không thể tạo báo thức vì thời điểm báo thức chưa đúng định dạng ngày giờ.",
                            "error_code": "alarm_invalid_datetime",
                            "user_hint": "Bạn hãy nói rõ ngày và giờ, ví dụ 6 giờ sáng ngày 21.",
                        },
                    }
                ],
            },
            runtime=SimpleNamespace(context=SimpleNamespace(llm=llm)),
        )

        self.assertEqual(result["response_text"], "Mình chưa đặt được báo thức. Bạn nói rõ ngày và giờ giúp mình nhé.")
        self.assertEqual(result["dialogue_action"], "ask_clarification")
        self.assertEqual(result["metadata"]["task_status"], "needs_clarification")
        self.assertEqual(result["session_state"]["active_task"]["pending"]["missing_fields"], ["scheduled_for"])
        self.assertEqual(len(llm.synthesis_calls), 1)


class WrapperRepairTests(unittest.TestCase):
    def test_normalize_tool_plan_accepts_tool_name_alias(self) -> None:
        wrapper = object.__new__(LLMWrapper)

        normalized = LLMWrapper._normalize_tool_plan(
            wrapper,
            [{"tool_name": "get_user_profile", "args": {}}],
        )

        self.assertEqual(normalized, [{"name": "get_user_profile", "parameters": {}}])

    def test_build_compact_tool_results_keeps_parameters_and_timing(self) -> None:
        wrapper = object.__new__(LLMWrapper)

        compact = LLMWrapper._build_compact_tool_results(
            wrapper,
            [
                {
                    "tool": "create_alarm",
                    "parameters": {"schedule_type": "datetime", "scheduled_for": "2026-04-21T06:00:00+07:00"},
                    "execution_time_ms": 12,
                    "result": {"status": "error", "message": "bad"},
                }
            ],
        )

        self.assertEqual(
            compact[0]["parameters"],
            {"schedule_type": "datetime", "scheduled_for": "2026-04-21T06:00:00+07:00"},
        )
        self.assertEqual(compact[0]["execution_time_ms"], 12)

    def test_run_group_agent_repairs_invalid_tool_name(self) -> None:
        wrapper = object.__new__(LLMWrapper)
        responses = iter(
            [
                SimpleNamespace(
                    content="""
{"assistant_text":"Mình bật timer cho bạn ngay.","dialogue_action":"use_tools","subtask":"timer.create","tool_plan":[{"name":"set_timer","parameters":{"duration":"10 phút"}}],"missing_fields":[],"slots":{},"confidence":0.81}
"""
                ),
                SimpleNamespace(
                    content="""
{"assistant_text":"Mình bật timer cho bạn ngay.","dialogue_action":"use_tools","subtask":"timer.create","tool_plan":[{"name":"start_timer","parameters":{"duration":"10 phút"}}],"missing_fields":[],"slots":{"duration":"10 phút"},"confidence":0.92}
"""
                ),
            ]
        )

        wrapper._invoke_with_instruction = lambda instruction, user_prompt: next(responses)

        result = LLMWrapper.run_group_agent(
            wrapper,
            group="productivity",
            user_input="bật timer 10 phút",
            user_name="Guest",
            current_time="2026-04-17 17:30:00",
            response_preferences="- preferred_output_language: vi-VN",
            user_profile="Name: Guest",
            task_summary="Chưa có ngữ cảnh task.",
            task_transcript="Chưa có lượt hội thoại nào trong task này.",
            conversation_summary="Chưa có ngữ cảnh cũ trước recent window.",
            conversation_transcript="Bắt đầu cuộc trò chuyện mới",
            tools_available=["start_timer"],
            session_mode="conversation",
            return_mode="conversation",
            pending_summary="không có",
        )

        self.assertEqual(result["dialogue_action"], "use_tools")
        self.assertEqual(
            result["tool_plan"],
            [{"name": "start_timer", "parameters": {"duration": "10 phút"}}],
        )


class PersonalizationClarificationTests(unittest.TestCase):
    def test_personalization_pending_clarification_can_be_resolved_by_small_llm(self) -> None:
        llm = FakePlannerLLM(
            clarification_result={
                "decision": "resolved",
                "assistant_text": "",
                "rewritten_user_input": "Kiểm tra tất cả thông tin cá nhân của tôi",
                "reason": "short_reply_expanded",
                "confidence": 0.94,
            }
        )

        result = nodes.personalization_agent(
            {
                "text_input": "Tất cả",
                "session_state": {
                    "mode": "conversation",
                    "active_task": {
                        "group": "personalization",
                        "return_mode": "conversation",
                        "subtask": "profile.read",
                        "transcript": [],
                        "summary": "Chưa có ngữ cảnh cũ trước recent window.",
                        "pending": {
                            "kind": "clarification",
                            "question": "Bạn muốn kiểm tra thông tin cá nhân nào của mình?",
                            "original_user_input": "Kiểm tra thông tin cá nhân của tôi",
                            "subtask": "profile.read",
                            "tool_plan": [],
                            "missing_fields": [],
                            "context": {},
                        },
                    }
                },
                "route_return_mode": "conversation",
            },
            runtime=SimpleNamespace(context=SimpleNamespace(llm=llm)),
        )

        self.assertEqual(result["dialogue_action"], "use_tools")
        self.assertEqual(result["metadata"]["subtask"], "profile.read")
        self.assertEqual(result["tool_calls"], [{"name": "get_user_profile", "parameters": {}}])
        self.assertEqual(len(llm.clarification_calls), 1)


class ProductivityToolResolutionTests(unittest.TestCase):
    def test_cancel_timer_resolves_single_active_timer_without_id(self) -> None:
        with patch.object(
            backend_tools,
            "_get_timers_data",
            return_value={"timers": [{"timer_id": "timer-1", "label": "Timer"}]},
        ), patch.object(backend_tools, "backend_request") as backend_request_mock:
            result = backend_tools.cancel_timer("nfc-1")

        backend_request_mock.assert_called_once_with("DELETE", "/api/users/nfc-1/timers/timer-1")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["timer_id"], "timer-1")

    def test_create_alarm_defaults_label_when_missing(self) -> None:
        with patch.object(
            backend_tools,
            "_get_alarms_data",
            return_value={"alarms": []},
        ), patch.object(
            backend_tools,
            "backend_json",
            return_value={
                "alarm_id": "alarm-1",
                "label": "Báo thức",
                "time": "07:00",
                "repeat": "once",
                "schedule_type": "time",
                "enabled": True,
            },
        ) as backend_json_mock:
            result = backend_tools.create_alarm("nfc-1", time="07:00")

        backend_json_mock.assert_called_once_with(
            "POST",
            "/api/users/nfc-1/alarms",
            json_payload={"label": "Báo thức", "repeat": "once", "time": "07:00"},
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["label"], "Báo thức")

    def test_create_alarm_detects_duplicate_existing_alarm_before_post(self) -> None:
        with patch.object(
            backend_tools,
            "_get_alarms_data",
            return_value={
                "alarms": [
                    {
                        "alarm_id": "alarm-1",
                        "label": "Báo thức",
                        "time": "07:00",
                        "repeat": "once",
                        "schedule_type": "time",
                        "enabled": True,
                    }
                ]
            },
        ), patch.object(backend_tools, "backend_json") as backend_json_mock:
            result = backend_tools.create_alarm("nfc-1", time="07:00")

        backend_json_mock.assert_not_called()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_code"], "alarm_already_exists")
        self.assertEqual(len(result["existing_matches"]), 1)

    def test_start_timer_detects_duplicate_existing_timer_before_post(self) -> None:
        with patch.object(
            backend_tools,
            "_get_timers_data",
            return_value={
                "timers": [
                    {
                        "timer_id": "timer-1",
                        "label": "Timer",
                        "duration_seconds": 600,
                        "active": True,
                    }
                ]
            },
        ), patch.object(backend_tools, "backend_json") as backend_json_mock:
            result = backend_tools.start_timer("nfc-1", "10 phút")

        backend_json_mock.assert_not_called()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_code"], "timer_already_exists")
        self.assertEqual(len(result["existing_matches"]), 1)

    def test_start_timer_ignores_expired_existing_timer(self) -> None:
        expired_started_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        with patch.object(
            backend_tools,
            "_get_timers_data",
            return_value={
                "timers": [
                    {
                        "timer_id": "timer-1",
                        "label": "Timer",
                        "duration_seconds": 20,
                        "started_at": expired_started_at,
                        "active": True,
                    }
                ]
            },
        ), patch.object(
            backend_tools,
            "backend_json",
            return_value={
                "timer_id": "timer-2",
                "label": "Timer",
                "duration_seconds": 20,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "active": True,
            },
        ) as backend_json_mock:
            result = backend_tools.start_timer("nfc-1", "20 giây")

        backend_json_mock.assert_called_once()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["timer_id"], "timer-2")

    def test_start_timer_surfaces_clean_user_not_found_error(self) -> None:
        with patch.object(
            backend_tools,
            "backend_json",
            side_effect=RuntimeError("User not found"),
        ):
            result = backend_tools.start_timer("nfc-1", "10 giay")

        self.assertEqual(result["status"], "error")
        self.assertEqual(
            result["message"],
            "Không thể bắt đầu timer vì chưa có hồ sơ người dùng cho thẻ NFC hiện tại.",
        )


class BackendCommonTests(unittest.TestCase):
    def test_backend_request_uses_backend_json_error_message(self) -> None:
        response = SimpleNamespace(
            status_code=404,
            reason="Not Found",
            json=lambda: {"error": "User not found"},
        )

        with patch.object(tool_common.requests, "request", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "User not found"):
                tool_common.backend_request("GET", "/api/users/tag-1")


if __name__ == "__main__":
    unittest.main()
