"""LangGraph 生产链路与 NDJSON Tool 进度事件测试。"""
from __future__ import annotations

import json
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage

from assistant.application.service import cancel_request, chat_stream, clear_all_conversations
from assistant.integrations.langchain.events import GraphStreamCancelled
from assistant.llm.config import ModelConfig
from test.test_assistant.fakes import (
    FailingChatModel,
    ScriptedChatModel,
    classification_message,
    tool_call_data,
    tool_call_message,
)


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
            stream=False,
        )

    def tearDown(self):
        clear_all_conversations()

    @patch("assistant.integrations.langchain.tools.execute_tool")
    @patch("assistant.application.service.create_chat_model")
    @patch("assistant.application.service.get_model_config")
    @patch("assistant.application.service.get_session")
    def test_stream_emits_tool_progress_and_structured_links(
        self, mocked_session, mocked_config, mocked_model, mocked_tool
    ):
        self._configure(mocked_session, mocked_config)
        mocked_model.return_value = ScriptedChatModel(responses=[
            classification_message("message_search"),
            tool_call_message("search_messages", {"service_id": "0x0A01"}, "call-1"),
            AIMessage(content="查询完成。"),
        ])
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
        self.assertIn("completed", event_types)
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
        self.assertTrue(result["run"]["graph_run_id"])
        self.assertGreater(result["run"]["graph_event_count"], 0)

    @patch("assistant.application.service.create_chat_model")
    @patch("assistant.application.service.get_model_config")
    @patch("assistant.application.service.get_session")
    def test_stream_without_tool_returns_answer_directly(
        self, mocked_session, mocked_config, mocked_model
    ):
        self._configure(mocked_session, mocked_config)
        mocked_model.return_value = ScriptedChatModel(responses=[
            classification_message("model_identity", requires_tools=False),
            AIMessage(content="直接回答。"),
        ])

        events = self._events("session-1", "你是什么模型")

        self.assertEqual(events[-1]["type"], "result")
        self.assertEqual(events[-1]["result"]["answer"], "直接回答。")
        self.assertEqual(events[-1]["result"]["tools"], [])

    @patch("assistant.integrations.langchain.tools.execute_tool")
    @patch("assistant.application.service.create_chat_model")
    @patch("assistant.application.service.get_model_config")
    @patch("assistant.application.service.get_session")
    def test_multiple_tool_calls_are_all_reported(
        self, mocked_session, mocked_config, mocked_model, mocked_tool
    ):
        self._configure(mocked_session, mocked_config)
        mocked_model.return_value = ScriptedChatModel(responses=[
            classification_message("service_lookup"),
            AIMessage(content="", tool_calls=[
                tool_call_data("find_service", {"query": "0x0A01"}, "call-1"),
                tool_call_data("get_subscription_status", {}, "call-2"),
            ]),
            AIMessage(content="综合回答。"),
        ])
        mocked_tool.return_value = {"ok": True}

        events = self._events("session-1", "综合查询")
        result = events[-1]["result"]

        self.assertCountEqual(
            [item["name"] for item in result["tools"]],
            ["find_service", "get_subscription_status"],
        )
        self.assertEqual(sum(event["type"] == "tool_start" for event in events), 2)

    @patch("assistant.integrations.langchain.tools.execute_tool")
    @patch("assistant.application.service.create_chat_model")
    @patch("assistant.application.service.get_model_config")
    @patch("assistant.application.service.get_session")
    def test_complex_web_request_runs_reflection_without_leaking_schema_output(
        self, mocked_session, mocked_config, mocked_model, mocked_tool
    ):
        self._configure(mocked_session, mocked_config)
        mocked_model.return_value = ScriptedChatModel(responses=[
            classification_message(
                "subscription_diagnostic",
                complexity="complex",
                answer_kind="report",
            ),
            tool_call_message("get_subscription_status", {}, "call-1"),
            AIMessage(content="订阅诊断报告。"),
            AIMessage(content="", tool_calls=[{
                "name": "ReflectionResult",
                "args": {
                    "passed": True,
                    "score": 0.98,
                    "missing_facts": [],
                    "unsupported_claims": [],
                    "evidence_gaps": [],
                    "format_issues": [],
                    "revision_instructions": [],
                    "needs_more_tools": False,
                },
                "id": "reflection-1",
                "type": "tool_call",
            }]),
        ])
        mocked_tool.return_value = {"summary": {"service_count": 1}}

        events = self._events("session-1", "生成订阅诊断报告")
        result = events[-1]["result"]

        self.assertEqual(result["answer"], "订阅诊断报告。")
        self.assertEqual(result["run"]["reflection_count"], 1)
        self.assertNotIn("ReflectionResult", "".join(
            event.get("delta", "") for event in events if event["type"] == "text_delta"
        ))

    @patch("assistant.application.service.create_chat_model")
    @patch("assistant.application.service.get_model_config")
    @patch("assistant.application.service.get_session")
    def test_model_failure_becomes_stream_error(
        self, mocked_session, mocked_config, mocked_model
    ):
        self._configure(mocked_session, mocked_config)
        mocked_model.return_value = FailingChatModel(responses=[])

        events = self._events("session-1", "测试失败")

        self.assertEqual(events[0]["type"], "context")
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["status_code"], 502)
        self.assertIn("模型调用失败", events[-1]["message"])

    @patch("assistant.application.service.run_agent_graph")
    @patch("assistant.application.service.create_chat_model")
    @patch("assistant.application.service.get_model_config")
    @patch("assistant.application.service.get_session")
    def test_active_stream_can_be_cancelled(
        self, mocked_session, mocked_config, mocked_model, mocked_graph
    ):
        self._configure(mocked_session, mocked_config)
        mocked_model.return_value = ScriptedChatModel(responses=[])
        started = Event()

        def wait_for_cancel(**kwargs):
            started.set()
            kwargs["cancel_event"].wait(2)
            raise GraphStreamCancelled("请求已取消")

        mocked_graph.side_effect = wait_for_cancel
        lines: list[str] = []
        worker = Thread(target=lambda: lines.extend(chat_stream(
            "session-1",
            "取消测试",
            request_id="request-cancel-test",
        )))
        worker.start()
        self.assertTrue(started.wait(1))
        self.assertTrue(cancel_request("request-cancel-test", "session-1"))
        worker.join(3)

        self.assertFalse(worker.is_alive())
        events = [json.loads(line) for line in lines]
        self.assertEqual(events[-1]["type"], "cancelled")

    def _configure(self, mocked_session, mocked_config) -> None:
        mocked_session.return_value = self.state
        mocked_config.return_value = self.config

    @staticmethod
    def _events(session_id: str, question: str) -> list[dict[str, Any]]:
        return [json.loads(line) for line in chat_stream(session_id, question)]


if __name__ == "__main__":
    unittest.main()
