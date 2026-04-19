from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest


SERVER_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_BACKEND_ROOT))

from assistant_core import nodes


class FakeInformationLLM:
    def __init__(
        self,
        *,
        planner_result: dict[str, object] | None = None,
        verify_result: dict[str, object] | None = None,
        synthesis_result: dict[str, object] | None = None,
    ) -> None:
        self.planner_result = planner_result or {}
        self.verify_result = verify_result or {}
        self.synthesis_result = synthesis_result or {}
        self.group_agent_calls: list[dict[str, object]] = []
        self.verify_calls: list[dict[str, object]] = []
        self.synthesis_calls: list[dict[str, object]] = []

    def run_group_agent(self, **kwargs):
        self.group_agent_calls.append(kwargs)
        return self.planner_result

    def verify_information_result(self, **kwargs):
        self.verify_calls.append(kwargs)
        return self.verify_result

    def synthesize_tool_results(self, **kwargs):
        self.synthesis_calls.append(kwargs)
        return self.synthesis_result


class InformationQueryFlowTests(unittest.TestCase):
    def test_merge_followup_prefers_rewritten_query_over_concatenation(self) -> None:
        merged = nodes._merge_followup_text("Giá vàng hôm nay", "Giá vàng thế giới")
        self.assertEqual(merged, "Giá vàng thế giới")

    def test_information_agent_searches_instead_of_generic_clarify(self) -> None:
        llm = FakeInformationLLM(
            planner_result={
                "assistant_text": "Mình tra cứu cho bạn ngay.",
                "dialogue_action": "use_tools",
                "subtask": "search_information",
                "tool_plan": [{"name": "web_search", "parameters": {"query": "giá vàng hôm nay", "max_results": 5}}],
                "missing_fields": [],
                "slots": {"query": "giá vàng hôm nay"},
                "confidence": 0.95,
            }
        )
        result = nodes.information_query_agent(
            {
                "text_input": "giá vàng hôm nay",
                "session_state": {"mode": "conversation"},
                "route_return_mode": "conversation",
            },
            runtime=SimpleNamespace(context=SimpleNamespace(llm=llm)),
        )

        self.assertEqual(result["dialogue_action"], "use_tools")
        self.assertEqual(result["metadata"]["subtask"], "search_information")
        self.assertEqual(
            result["tool_calls"],
            [{"name": "web_search", "parameters": {"query": "giá vàng hôm nay", "max_results": 5}}],
        )

    def test_information_handle_tool_results_can_refine_search_instead_of_clarify(self) -> None:
        llm = FakeInformationLLM(
            verify_result={
                "decision": "refine_search",
                "assistant_text": "",
                "reason": "need_narrower_gold_reference",
                "confidence": 0.88,
                "missing_fields": [],
                "refined_query": "giá vàng miếng sjc hôm nay",
            }
        )
        result = nodes.handle_tool_results(
            {
                "route_group": "information_query",
                "route_return_mode": "conversation",
                "session_state": {"mode": "conversation"},
                "task_input": "giá vàng hôm nay",
                "metadata": {"group": "information_query", "subtask": "search_information", "confidence": 0.9},
                "tool_results": [
                    {
                        "tool": "web_search",
                        "result": {
                            "status": "success",
                            "ambiguity_hint": {
                                "should_clarify": True,
                                "question": "Bạn muốn xem giá vàng miếng SJC, vàng nhẫn/9999 trong nước, hay giá vàng thế giới?",
                                "missing_fields": ["gold_reference_type"],
                                "options": ["giá vàng miếng SJC trong nước", "giá vàng thế giới"],
                            },
                            "summary_candidates": [],
                            "content_items": [],
                        },
                    }
                ],
            },
            runtime=SimpleNamespace(context=SimpleNamespace(llm=llm)),
        )

        self.assertEqual(result["dialogue_action"], "use_tools")
        self.assertEqual(result["metadata"]["task_status"], "in_progress")
        self.assertEqual(
            result["tool_calls"],
            [{"name": "web_search", "parameters": {"query": "giá vàng miếng sjc hôm nay", "max_results": 5}}],
        )

    def test_information_handle_tool_results_answers_when_verifier_says_answer(self) -> None:
        llm = FakeInformationLLM(
            verify_result={
                "decision": "answer",
                "assistant_text": "Theo kết quả tìm kiếm, giá vàng miếng SJC đang là trọng tâm chính.",
                "reason": "dominant_interpretation_available",
                "confidence": 0.9,
                "missing_fields": [],
                "refined_query": "",
                "answer_style": "detailed",
                "follow_up_mode": "none",
                "should_strip_follow_up_offer": True,
                "answer_outline": ["mốc giá chính", "nguồn chính", "framing theo SJC"],
            },
            synthesis_result={
                "assistant_text": "Theo các nguồn tìm được, giá vàng miếng SJC hiện là mốc được nhắc nhiều nhất trong kết quả.",
                "dialogue_action": "respond_only",
                "missing_fields": [],
                "confidence": 0.92,
            },
        )
        result = nodes.handle_tool_results(
            {
                "route_group": "information_query",
                "route_return_mode": "conversation",
                "session_state": {"mode": "conversation"},
                "task_input": "giá vàng hôm nay",
                "metadata": {"group": "information_query", "subtask": "search_information", "confidence": 0.9},
                "tool_results": [
                    {
                        "tool": "web_search",
                        "result": {
                            "status": "success",
                            "summary_candidates": [
                                {"domain": "sjc.com.vn", "title": "Giá vàng hôm nay", "excerpt": "Giá vàng miếng SJC ..."}
                            ],
                            "content_items": [],
                        },
                    }
                ],
            },
            runtime=SimpleNamespace(context=SimpleNamespace(llm=llm)),
        )

        self.assertEqual(result["dialogue_action"], "respond_only")
        self.assertEqual(result["metadata"]["task_status"], "completed")
        self.assertIn("SJC", result["response_text"])
        self.assertEqual(llm.synthesis_calls[0]["answer_policy"]["answer_style"], "detailed")
        self.assertEqual(llm.synthesis_calls[0]["answer_policy"]["follow_up_mode"], "none")

    def test_information_follow_up_offer_does_not_create_pending_clarification(self) -> None:
        llm = FakeInformationLLM(
            verify_result={
                "decision": "answer",
                "assistant_text": "",
                "reason": "enough_evidence",
                "confidence": 0.9,
                "missing_fields": [],
                "refined_query": "",
                "answer_style": "balanced",
                "follow_up_mode": "none",
                "should_strip_follow_up_offer": True,
                "answer_outline": [],
            },
            synthesis_result={
                "assistant_text": (
                    "Dạ giá vàng thế giới hôm nay tăng nhẹ khoảng 0.95 phần trăm, tương đương 45.62 USD mỗi ounce. "
                    "Bạn có muốn biết thêm thông tin gì không nè"
                ),
                "dialogue_action": "respond_only",
                "missing_fields": [],
                "confidence": 0.92,
            },
        )
        result = nodes.handle_tool_results(
            {
                "route_group": "information_query",
                "route_return_mode": "conversation",
                "session_state": {"mode": "conversation"},
                "task_input": "Giá vàng thế giới",
                "metadata": {"group": "information_query", "subtask": "search_information", "confidence": 0.9},
                "tool_results": [
                    {
                        "tool": "web_search",
                        "result": {
                            "status": "success",
                            "summary_candidates": [
                                {
                                    "domain": "giavang.org",
                                    "title": "Giá vàng thế giới hôm nay",
                                    "excerpt": "Giá vàng thế giới nhìn chung có tăng 0.95% trong 24 giờ qua.",
                                }
                            ],
                            "content_items": [],
                        },
                    }
                ],
            },
            runtime=SimpleNamespace(context=SimpleNamespace(llm=llm)),
        )

        self.assertEqual(result["dialogue_action"], "respond_only")
        self.assertEqual(result["metadata"]["task_status"], "completed")
        self.assertFalse(result["needs_clarification"])
        self.assertNotIn("muốn biết thêm", result["response_text"].lower())

    def test_trim_trailing_detail_follow_up_offer(self) -> None:
        trimmed = nodes._trim_trailing_follow_up_offer(
            "Hiện tại tình hình Trung Đông đang khá căng thẳng. Bạn có muốn mình kể chi tiết hơn không"
        )
        self.assertNotIn("muốn mình kể chi tiết hơn", trimmed.lower())
        self.assertIn("Trung Đông", trimmed)


if __name__ == "__main__":
    unittest.main()
