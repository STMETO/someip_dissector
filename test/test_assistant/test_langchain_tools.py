"""第二阶段 LangChain Tool 适配与治理测试。"""
from __future__ import annotations

from collections.abc import Sequence
import json
from threading import Event
from typing import Any
import unittest
from unittest.mock import patch

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr, ValidationError

from assistant.agent.context import SomeIpAgentContext
from assistant.execution.run_record import AssistantRunRecord
from assistant.integrations.langchain import (
    LANGCHAIN_TOOL_MAP,
    LANGCHAIN_TOOLS,
    create_tool_context,
    someip_tool_middleware,
)
from assistant.integrations.langchain.tool_schemas import TOOL_ARGS_SCHEMAS
from assistant.tools import TOOL_DEFINITIONS


class _ScriptedChatModel(BaseChatModel):
    """用固定消息驱动 LangChain Agent，不访问真实模型网络。"""

    responses: list[AIMessage]
    _bound_tools: list[Any] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "someip-tool-scripted-test"

    def _generate(
        self,
        _messages,
        stop=None,
        run_manager=None,
        **_kwargs,
    ) -> ChatResult:
        del stop, run_manager
        if not self.responses:
            raise AssertionError("测试模型没有剩余脚本响应")
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])

    def bind_tools(
        self,
        tools: Sequence[Any],
        **_kwargs,
    ) -> "_ScriptedChatModel":
        self._bound_tools = list(tools)
        return self


class LangChainToolTests(unittest.TestCase):
    """验证新 Tool 与旧白名单契约一致，且运行时边界不可由模型控制。"""

    def test_all_legacy_tools_have_matching_pydantic_schemas(self):
        legacy = {
            item["function"]["name"]: item["function"]["parameters"]
            for item in TOOL_DEFINITIONS
        }

        self.assertEqual(len(LANGCHAIN_TOOLS), 14)
        self.assertEqual(set(legacy), set(TOOL_ARGS_SCHEMAS))
        self.assertEqual(set(legacy), set(LANGCHAIN_TOOL_MAP))
        for name, old_schema in legacy.items():
            new_schema = LANGCHAIN_TOOL_MAP[name].tool_call_schema.model_json_schema()
            self.assertEqual(
                set(old_schema.get("properties", {})),
                set(new_schema.get("properties", {})),
                name,
            )
            self.assertEqual(
                set(old_schema.get("required", [])),
                set(new_schema.get("required", [])),
                name,
            )
            args_schema = TOOL_ARGS_SCHEMAS[name].model_json_schema()
            self.assertEqual(args_schema.get("additionalProperties"), False, name)

    def test_model_schema_hides_server_runtime_dependencies(self):
        forbidden = {
            "allowed_session_ids",
            "api_key",
            "budget",
            "cancel_event",
            "current_session_id",
            "file_path",
            "model_config",
            "queries",
            "session_queries",
            "tool_executor",
        }
        for tool in LANGCHAIN_TOOLS:
            properties = set(tool.tool_call_schema.model_json_schema()["properties"])
            self.assertTrue(properties.isdisjoint(forbidden), tool.name)

        # 该参数是 SOME/IP 报文头的 Session ID，不是服务器解析会话 ID。
        request_schema = LANGCHAIN_TOOL_MAP[
            "get_request_response_trace"
        ].tool_call_schema.model_json_schema()
        self.assertIn("session_id", request_schema["properties"])

    def test_pydantic_schemas_reject_unknown_and_out_of_range_arguments(self):
        with self.assertRaises(ValidationError):
            TOOL_ARGS_SCHEMAS["find_service"].model_validate({"limit": 51})
        with self.assertRaises(ValidationError):
            TOOL_ARGS_SCHEMAS["get_offer_timeline"].model_validate({
                "service_id": "0x0A01",
                "start_time": 20,
                "end_time": 10,
            })
        with self.assertRaises(ValidationError):
            TOOL_ARGS_SCHEMAS["search_messages"].model_validate({
                "shell_command": "rm -rf /",
            })

    def test_agent_invokes_tool_with_runtime_context_and_uniform_envelope(self):
        calls: list[tuple[str, dict[str, Any], str]] = []

        def handler(name: str, arguments: dict[str, Any], session_id: str):
            calls.append((name, arguments, session_id))
            return {
                "matched_service_count": 1,
                "services": [{"service_id": "0x0A01", "name": "Parking"}],
            }

        context = create_tool_context(
            "capture-a",
            _run_record(),
            tool_handler=handler,
        )
        result = _run_agent(
            "find_service",
            {"query": "Parking"},
            context,
        )

        self.assertEqual(calls, [(
            "find_service",
            {"query": "Parking", "limit": 20},
            "capture-a",
        )])
        message = _only_tool_message(result)
        envelope = json.loads(str(message.content))
        self.assertEqual(envelope["data"], message.artifact["result"])
        self.assertEqual(envelope["summary"], {"matched_service_count": 1})
        self.assertEqual(envelope["evidence"], message.artifact["evidence"])
        self.assertEqual(envelope["evidence"][0]["service_id"], 0x0A01)
        self.assertIsNone(envelope["error"])
        self.assertFalse(envelope["truncated"])
        self.assertEqual(message.status, "success")
        self.assertEqual(message.artifact["execution"]["status"], "success")

    def test_large_result_is_compacted_for_model_but_complete_in_artifact(self):
        rows = [{"index": index, "value": "x" * 50} for index in range(80)]

        def handler(_name: str, _arguments: dict[str, Any], _session_id: str):
            return {"matched_message_count": 80, "messages": rows}

        result = _run_agent(
            "search_messages",
            {},
            create_tool_context("capture-a", _run_record(), tool_handler=handler),
        )
        message = _only_tool_message(result)
        envelope = json.loads(str(message.content))

        self.assertEqual(len(envelope["data"]["messages"]), 50)
        self.assertEqual(len(message.artifact["result"]["messages"]), 80)
        self.assertTrue(envelope["truncated"])
        self.assertTrue(any("offset" in item for item in envelope["warnings"]))

    def test_middleware_returns_safe_error_for_invalid_model_arguments(self):
        called = False

        def handler(_name: str, _arguments: dict[str, Any], _session_id: str):
            nonlocal called
            called = True
            return {}

        result = _run_agent(
            "find_service",
            {"limit": 999},
            create_tool_context("capture-a", _run_record(), tool_handler=handler),
        )
        message = _only_tool_message(result)
        envelope = json.loads(str(message.content))

        self.assertFalse(called)
        self.assertEqual(message.status, "error")
        self.assertEqual(envelope["error"]["code"], "invalid_arguments")
        self.assertNotIn("999", str(message.artifact))

    def test_cross_session_authorization_is_injected_by_server(self):
        observed: list[tuple[str, dict[str, Any], str, frozenset[str]]] = []

        def fake_execute(name, arguments, session_id, allowed_session_ids=()):
            observed.append((name, arguments, session_id, frozenset(allowed_session_ids)))
            return {"session_count": 2, "sessions": [session_id, *arguments["session_ids"]]}

        with patch("assistant.integrations.langchain.tools.execute_tool", fake_execute):
            context = create_tool_context(
                "capture-a",
                _run_record(),
                allowed_session_ids=["capture-b"],
            )
            result = _run_agent(
                "compare_sessions",
                {"session_ids": ["capture-b"]},
                context,
            )

        self.assertEqual(observed, [(
            "compare_sessions",
            {"session_ids": ["capture-b"]},
            "capture-a",
            frozenset({"capture-b"}),
        )])
        self.assertEqual(_only_tool_message(result).status, "success")

    def test_controlled_executor_failure_keeps_envelope_and_marks_error(self):
        def handler(_name: str, _arguments: dict[str, Any], _session_id: str):
            raise ValueError("字段不存在")

        result = _run_agent(
            "get_payload_field",
            {"message_index": 7, "field_path": "missing.path"},
            create_tool_context("capture-a", _run_record(), tool_handler=handler),
        )
        message = _only_tool_message(result)
        envelope = json.loads(str(message.content))

        self.assertEqual(message.status, "error")
        self.assertEqual(envelope["error"]["code"], "tool_error")
        self.assertEqual(message.artifact["execution"]["status"], "failed")

    def test_cancel_signal_stops_tool_before_handler_execution(self):
        called = False

        def handler(_name: str, _arguments: dict[str, Any], _session_id: str):
            nonlocal called
            called = True
            return {}

        cancel_event = Event()
        cancel_event.set()
        result = _run_agent(
            "find_service",
            {},
            create_tool_context(
                "capture-a",
                _run_record(),
                cancel_event=cancel_event,
                tool_handler=handler,
            ),
        )
        message = _only_tool_message(result)
        envelope = json.loads(str(message.content))

        self.assertFalse(called)
        self.assertEqual(message.status, "error")
        self.assertEqual(envelope["error"]["code"], "cancelled")


def _run_agent(
    tool_name: str,
    arguments: dict[str, Any],
    context: SomeIpAgentContext,
) -> dict[str, Any]:
    """执行一次模型 Tool Call，再由第二条脚本消息结束 Agent。"""
    model = _ScriptedChatModel(responses=[
        AIMessage(
            content="",
            tool_calls=[{
                "name": tool_name,
                "args": arguments,
                "id": "tool-call-1",
                "type": "tool_call",
            }],
        ),
        AIMessage(content="done"),
    ])
    agent = create_agent(
        model=model,
        tools=list(LANGCHAIN_TOOLS),
        middleware=[someip_tool_middleware],
        context_schema=SomeIpAgentContext,
    )
    return agent.invoke(
        {"messages": [{"role": "user", "content": "测试"}]},
        context=context,
    )


def _only_tool_message(result: dict[str, Any]) -> ToolMessage:
    messages = [item for item in result["messages"] if item.type == "tool"]
    if len(messages) != 1:
        raise AssertionError(f"预期一条 ToolMessage，实际 {len(messages)} 条")
    return messages[0]


def _run_record() -> AssistantRunRecord:
    return AssistantRunRecord(
        request_id="test-request",
        session_id="capture-a",
        model="fake-model",
        prompt_version="test",
        answer_contract_version="test",
    )


if __name__ == "__main__":
    unittest.main()
