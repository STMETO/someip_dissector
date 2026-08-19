"""AI 编排层第五阶段可靠性回归测试。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from assistant.llm.config import ModelConfig
from assistant.evaluation import load_evaluation_cases
from assistant.answering.prompts import (
    ANSWER_CONTRACT_VERSION,
    PROMPT_VERSION,
    render_system_prompt,
)
from assistant.application.service import chat_stream, clear_all_conversations


class AssistantReliabilityTests(unittest.TestCase):
    def setUp(self):
        clear_all_conversations()
        self.state = SimpleNamespace(
            session_id="session-reliability",
            session_dir=Path("/tmp/assistant-reliability-test"),
            persistent=False,
            total_messages=8,
            pcap_name="fixture.pcap",
        )
        self.config = ModelConfig(
            api_key="secret-key-must-not-appear",
            api_base="https://example.invalid",
            model="test-model",
            timeout_seconds=5.0,
            source="runtime",
        )

    def tearDown(self):
        clear_all_conversations()

    @patch("assistant.application.service.execute_tool")
    @patch("assistant.application.service.create_chat_completion")
    @patch("assistant.application.service.get_model_config")
    @patch("assistant.application.service.get_session")
    def test_invalid_tool_arguments_return_limit_notice(
        self, mocked_session, mocked_config, mocked_completion, mocked_tool
    ):
        self._configure(mocked_session, mocked_config)
        mocked_completion.side_effect = [
            self._tool_call("get_offer_timeline", "{}"),
            {"role": "assistant", "content": "没有足够信息。"},
        ]

        result = self._events("检查 Offer")[ -1]["result"]

        self.assertEqual(result["tools"][0]["status"], "failed")
        self.assertEqual(result["tools"][0]["error_code"], "invalid_arguments")
        self.assertIn("### 查询限制", result["answer"])
        mocked_tool.assert_not_called()

    @patch("assistant.application.service.execute_tool")
    @patch("assistant.application.service.create_chat_completion")
    @patch("assistant.application.service.get_model_config")
    @patch("assistant.application.service.get_session")
    def test_empty_tool_result_is_a_successful_query(
        self, mocked_session, mocked_config, mocked_completion, mocked_tool
    ):
        self._configure(mocked_session, mocked_config)
        mocked_completion.side_effect = [
            self._tool_call("search_messages", "{}"),
            {"role": "assistant", "content": "抓包中没有匹配报文。"},
        ]
        mocked_tool.return_value = {"matched_message_count": 0, "messages": []}

        result = self._events("查询不存在的报文")[-1]["result"]

        self.assertEqual(result["tools"][0]["status"], "success")
        self.assertNotIn("查询限制", result["answer"])

    @patch("assistant.application.service.execute_tool")
    @patch("assistant.application.service.create_chat_completion")
    @patch("assistant.application.service.get_model_config")
    @patch("assistant.application.service.get_session")
    def test_unverified_model_navigation_links_are_removed(
        self, mocked_session, mocked_config, mocked_completion, mocked_tool
    ):
        self._configure(mocked_session, mocked_config)
        mocked_completion.side_effect = [
            self._tool_call("search_messages", "{}"),
            {
                "role": "assistant",
                "content": (
                    "[Message 4](#someip-message-4) 有效；"
                    "[Message 999](#someip-message-999) 无效；"
                    "[Service 0xBBBB](#someip-service-0xBBBB) 无效。"
                ),
            },
        ]
        mocked_tool.return_value = {
            "messages": [{"message_index": 4, "frame_index": 104}]
        }

        result = self._events("查询报文")[-1]["result"]

        self.assertIn("[Message 4](#someip-message-4)", result["answer"])
        self.assertNotIn("#someip-message-999", result["answer"])
        self.assertNotIn("#someip-service-0xBBBB", result["answer"])
        self.assertEqual(result["run"]["invalid_navigation_link_count"], 2)

    @patch("assistant.application.service.execute_tool")
    @patch("assistant.application.service.create_chat_completion")
    @patch("assistant.application.service.get_model_config")
    @patch("assistant.application.service.get_session")
    def test_model_tool_loop_is_stopped_by_round_budget(
        self, mocked_session, mocked_config, mocked_completion, mocked_tool
    ):
        self._configure(mocked_session, mocked_config)
        mocked_completion.return_value = self._tool_call("find_service", "{}")
        mocked_tool.return_value = {"services": []}

        with patch.dict(os.environ, {"AI_MAX_MODEL_ROUNDS": "2"}):
            events = self._events("持续循环")

        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("连续 2 轮", events[-1]["message"])
        self.assertEqual(mocked_completion.call_count, 2)

    def test_prompt_is_versioned_and_contains_answer_contract(self):
        prompt = render_system_prompt(
            self.state,
            self.config,
            "openai_compatible",
            [{"session_id": "allowed-session", "pcap_name": "target.pcap"}],
        )

        self.assertEqual(PROMPT_VERSION, "someip-agent-v1")
        self.assertEqual(ANSWER_CONTRACT_VERSION, "diagnostic-answer-v1")
        self.assertIn("抓包事实", prompt)
        self.assertIn("项目诊断规则", prompt)
        self.assertIn("可能原因", prompt)
        self.assertIn("Tool 返回 partial 或 error", prompt)
        self.assertIn("allowed-session", prompt)
        self.assertIn("target.pcap", prompt)

    @patch("assistant.application.service.create_chat_completion")
    @patch("assistant.application.service.get_model_config")
    @patch("assistant.application.service.get_session")
    def test_run_record_contains_metrics_but_no_sensitive_body(
        self, mocked_session, mocked_config, mocked_completion
    ):
        self._configure(mocked_session, mocked_config)
        mocked_completion.return_value = {
            "role": "assistant",
            "content": "安全回答正文",
            "_usage": {"prompt_tokens": 12, "completion_tokens": 3},
        }

        result = self._events("敏感问题正文")[-1]["result"]
        serialized = json.dumps(result["run"], ensure_ascii=False)

        self.assertEqual(result["run"]["request_id"], "request-reliability")
        self.assertEqual(result["run"]["model_rounds"], 1)
        self.assertEqual(result["run"]["token_usage"]["prompt_tokens"], 12)
        self.assertIn("max_tool_calls", result["run"]["execution_budget"])
        self.assertNotIn("secret-key-must-not-appear", serialized)
        self.assertNotIn("敏感问题正文", serialized)
        self.assertNotIn("安全回答正文", serialized)

    def test_fixed_evaluation_set_covers_base_and_extended_tools(self):
        cases = load_evaluation_cases()

        self.assertEqual(len(cases), 12)
        self.assertEqual(
            {case.case_id for case in cases},
            {
                "offer-conflict",
                "subscribe-without-offer",
                "subscribe-without-ack",
                "subscription-nack",
                "subscribed-without-notification",
                "healthy-subscription-chain",
                "request-response-trace",
                "ecu-service-topology",
                "arxml-definition",
                "payload-value-search",
                "anomaly-details",
                "session-comparison",
            },
        )
        for case in cases:
            self.assertTrue(case.expected_tools)
            self.assertTrue(case.required_facts)
            self.assertTrue(case.forbidden_claims)
            self.assertTrue(case.allowed_evidence)

    def _configure(self, mocked_session, mocked_config):
        mocked_session.return_value = self.state
        mocked_config.return_value = self.config

    def _events(self, question: str) -> list[dict]:
        return [
            json.loads(line)
            for line in chat_stream(
                self.state.session_id,
                question,
                request_id="request-reliability",
            )
        ]

    @staticmethod
    def _tool_call(name: str, arguments: str) -> dict:
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call-1",
                "function": {"name": name, "arguments": arguments},
            }],
        }


if __name__ == "__main__":
    unittest.main()
