"""AI 编排层 Tool 进度事件流测试。"""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from assistant.config import ModelConfig
from assistant.provider import ModelProviderError
from assistant.service import chat_stream, clear_all_conversations


class AssistantStreamTests(unittest.TestCase):
    def setUp(self):
        clear_all_conversations()
        self.state = SimpleNamespace(
            total_messages=4,
            pcap_name="fixture.pcap",
        )
        self.config = ModelConfig(
            api_key="test-key",
            api_base="https://example.invalid",
            model="test-model",
            timeout_seconds=5.0,
            source="runtime",
        )

    def tearDown(self):
        clear_all_conversations()

    @patch("assistant.service.execute_tool")
    @patch("assistant.service.create_chat_completion")
    @patch("assistant.service.get_model_config")
    @patch("assistant.service.get_session")
    def test_stream_emits_tool_progress_and_structured_links(
        self,
        mocked_session,
        mocked_config,
        mocked_completion,
        mocked_tool,
    ):
        mocked_session.return_value = self.state
        mocked_config.return_value = self.config
        mocked_completion.side_effect = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call-1",
                    "function": {
                        "name": "search_messages",
                        "arguments": '{"service_id":"0x0A01"}',
                    },
                }],
            },
            {"role": "assistant", "content": "查询完成。"},
        ]
        mocked_tool.return_value = {
            "messages": [{
                "service_id": "0x0A01",
                "message_index": 4,
                "frame_index": 104,
            }],
        }

        events = self._events("session-1", "查询服务")

        self.assertEqual(
            [event["type"] for event in events],
            ["status", "tool_start", "tool_end", "result"],
        )
        self.assertTrue(events[2]["ok"])
        result = events[-1]["result"]
        self.assertEqual(result["answer"], "查询完成。")
        self.assertEqual(result["model"], "test-model")
        self.assertEqual(result["tools"][0]["name"], "search_messages")
        self.assertTrue(any(
            link["kind"] == "message" and link["message_index"] == 4
            for link in result["tools"][0]["links"]
        ))

    @patch("assistant.service.create_chat_completion")
    @patch("assistant.service.get_model_config")
    @patch("assistant.service.get_session")
    def test_provider_failure_becomes_stream_error(
        self,
        mocked_session,
        mocked_config,
        mocked_completion,
    ):
        mocked_session.return_value = self.state
        mocked_config.return_value = self.config
        mocked_completion.side_effect = ModelProviderError("上游连接失败")

        events = self._events("session-1", "测试失败")

        self.assertEqual([event["type"] for event in events], ["status", "error"])
        self.assertEqual(events[-1]["status_code"], 502)
        self.assertEqual(events[-1]["message"], "上游连接失败")

    @staticmethod
    def _events(session_id: str, question: str) -> list[dict]:
        """消费 NDJSON 生成器并还原为事件对象。"""
        return [json.loads(line) for line in chat_stream(session_id, question)]


if __name__ == "__main__":
    unittest.main()
