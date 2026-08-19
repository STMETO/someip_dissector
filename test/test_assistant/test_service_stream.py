"""AI 编排层 Tool 进度事件流测试。"""
from __future__ import annotations

import json
from pathlib import Path
from threading import Event, Thread
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from assistant.llm.config import ModelConfig
from assistant.llm.gateway import ModelProviderError
from assistant.application.service import cancel_request, chat_stream, clear_all_conversations


class AssistantStreamTests(unittest.TestCase):
    def setUp(self):
        clear_all_conversations()
        self.state = SimpleNamespace(
            session_id="session-1",
            session_dir=Path("/tmp/assistant-stream-test"),
            persistent=False,
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

    @patch("assistant.application.service.execute_tool")
    @patch("assistant.application.service.create_chat_completion")
    @patch("assistant.application.service.get_model_config")
    @patch("assistant.application.service.get_session")
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

        event_types = [event["type"] for event in events]
        self.assertEqual(event_types[0], "context")
        self.assertIn("tool_start", event_types)
        self.assertIn("tool_end", event_types)
        self.assertIn("text_delta", event_types)
        self.assertEqual(event_types[-1], "result")
        tool_end = next(event for event in events if event["type"] == "tool_end")
        self.assertTrue(tool_end["ok"])
        result = events[-1]["result"]
        self.assertEqual(result["answer"], "查询完成。")
        self.assertEqual(result["model"], "test-model")
        self.assertEqual(result["tools"][0]["name"], "search_messages")
        self.assertTrue(any(
            link["kind"] == "message" and link["message_index"] == 4
            for link in result["tools"][0]["links"]
        ))

    @patch("assistant.application.service.create_chat_completion")
    @patch("assistant.application.service.get_model_config")
    @patch("assistant.application.service.get_session")
    def test_stream_without_tool_returns_answer_directly(
        self,
        mocked_session,
        mocked_config,
        mocked_completion,
    ):
        mocked_session.return_value = self.state
        mocked_config.return_value = self.config
        mocked_completion.return_value = {
            "role": "assistant",
            "content": "直接回答。",
        }

        events = self._events("session-1", "你是什么模型")

        self.assertEqual(events[-1]["type"], "result")
        self.assertEqual(events[-1]["result"]["answer"], "直接回答。")
        self.assertEqual(events[-1]["result"]["tools"], [])

    @patch("assistant.application.service.execute_tool")
    @patch("assistant.application.service.create_chat_completion")
    @patch("assistant.application.service.get_model_config")
    @patch("assistant.application.service.get_session")
    def test_multiple_tool_calls_are_all_reported(
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
                "tool_calls": [
                    {
                        "id": "call-1",
                        "function": {"name": "find_service", "arguments": '{"query":"0x0A01"}'},
                    },
                    {
                        "id": "call-2",
                        "function": {"name": "get_subscription_status", "arguments": "{}"},
                    },
                ],
            },
            {"role": "assistant", "content": "综合回答。"},
        ]
        mocked_tool.return_value = {"ok": True}

        events = self._events("session-1", "综合查询")
        result = events[-1]["result"]

        self.assertEqual(
            [item["name"] for item in result["tools"]],
            ["find_service", "get_subscription_status"],
        )
        self.assertEqual(
            sum(event["type"] == "tool_start" for event in events),
            2,
        )

    @patch("assistant.application.service.create_chat_completion")
    @patch("assistant.application.service.get_model_config")
    @patch("assistant.application.service.get_session")
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

        self.assertEqual(
            [event["type"] for event in events],
            ["context", "text_reset", "error"],
        )
        self.assertEqual(events[-1]["status_code"], 502)
        self.assertEqual(events[-1]["message"], "上游连接失败")

    @patch("assistant.application.service.create_chat_completion")
    @patch("assistant.application.service.get_model_config")
    @patch("assistant.application.service.get_session")
    def test_active_stream_can_be_cancelled(
        self,
        mocked_session,
        mocked_config,
        mocked_completion,
    ):
        mocked_session.return_value = self.state
        mocked_config.return_value = self.config
        started = Event()

        def wait_for_cancel(*_args, **kwargs):
            started.set()
            cancel_event = kwargs["cancel_event"]
            cancel_event.wait(2)
            raise ModelProviderError("请求已取消")

        mocked_completion.side_effect = wait_for_cancel
        lines = []
        worker = Thread(
            target=lambda: lines.extend(chat_stream(
                "session-1",
                "取消测试",
                request_id="request-cancel-test",
            )),
        )
        worker.start()
        self.assertTrue(started.wait(1))
        self.assertTrue(cancel_request("request-cancel-test", "session-1"))
        worker.join(3)

        self.assertFalse(worker.is_alive())
        events = [json.loads(line) for line in lines]
        self.assertEqual(events[-1]["type"], "cancelled")

    @staticmethod
    def _events(session_id: str, question: str) -> list[dict]:
        """消费 NDJSON 生成器并还原为事件对象。"""
        return [json.loads(line) for line in chat_stream(session_id, question)]


if __name__ == "__main__":
    unittest.main()
