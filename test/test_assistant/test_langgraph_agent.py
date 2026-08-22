"""第三阶段 SOME/IP LangGraph 主图测试。"""
from __future__ import annotations

from collections.abc import Sequence
from threading import Event
from types import SimpleNamespace
from typing import Any
import unittest

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from assistant.agent import AgentRoute, build_someip_agent_graph, state_route
from assistant.execution.run_record import AssistantRunRecord
from assistant.execution.tool_executor import ToolExecutionBudget
from assistant.integrations.langchain import create_tool_context


class _ScriptedChatModel(BaseChatModel):
    """按顺序返回脚本消息，并记录实际绑定的 Tool 子集。"""

    responses: list[AIMessage]
    _bound_tools: list[Any] = PrivateAttr(default_factory=list)
    _invocation_count: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "someip-langgraph-scripted-test"

    @property
    def invocation_count(self) -> int:
        return self._invocation_count

    @property
    def bound_tool_names(self) -> list[str]:
        names = []
        for tool in self._bound_tools:
            if hasattr(tool, "name"):
                names.append(str(tool.name))
            elif isinstance(tool, dict):
                names.append(str(tool.get("function", {}).get("name") or tool.get("name")))
        return names

    def _generate(
        self,
        _messages,
        stop=None,
        run_manager=None,
        **_kwargs,
    ) -> ChatResult:
        del stop, run_manager
        self._invocation_count += 1
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


class SomeIpLangGraphTests(unittest.TestCase):
    """验证外层确定性路由和内层 ReAct 的完整行为。"""

    def test_direct_answer_skips_all_domain_tools(self):
        classifier = _classifier("model_identity", requires_tools=False)
        direct = _ScriptedChatModel(responses=[AIMessage(content="当前配置模型为 test-model。")])
        main = _ScriptedChatModel(responses=[])
        graph = build_someip_agent_graph(
            main,
            system_prompt="你是测试助手，模型为 test-model。",
            classifier_model=classifier,
            direct_answer_model=direct,
        )
        context = _context(lambda *_args: self.fail("直接回答不应调用 Tool"))

        result = graph.invoke(
            {"messages": [{"role": "user", "content": "你是什么模型？"}]},
            context=context,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["final_answer"], "当前配置模型为 test-model。")
        self.assertEqual(result["selected_tools"], [])
        self.assertEqual(main.invocation_count, 0)
        self.assertEqual(context.tool_executor.run_record.model_rounds, 2)

    def test_single_tool_react_collects_trace_and_evidence(self):
        classifier = _classifier(
            "subscription_diagnostic",
            entities={"service_id": "0x0A01"},
        )
        main = _ScriptedChatModel(responses=[
            _tool_call("get_subscription_status", {"service_id": "0x0A01"}, "call-1"),
            AIMessage(content="服务 0x0A01 的订阅链路正常。"),
        ])
        calls = []

        def handler(name, arguments, session_id):
            calls.append((name, arguments, session_id))
            return {
                "matched_service_count": 1,
                "services": [{"service_id": "0x0A01", "offer_observed": True}],
            }

        context = _context(handler)
        result = _graph(main, classifier).invoke(
            {"messages": [{"role": "user", "content": "检查 0x0A01 的订阅状态"}]},
            context=context,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["tool_trace"]), 1)
        self.assertEqual(result["tool_trace"][0]["name"], "get_subscription_status")
        self.assertEqual(result["evidence"][0]["service_id"], 0x0A01)
        self.assertEqual(calls[0][2], "capture-a")
        self.assertIn("get_subscription_timeline", main.bound_tool_names)
        self.assertNotIn("search_payload_values", main.bound_tool_names)

    def test_multiple_tools_with_one_failure_routes_to_partial_answer(self):
        classifier = _classifier("offer_analysis", entities={"service_id": "0x0A01"})
        main = _ScriptedChatModel(responses=[
            AIMessage(content="", tool_calls=[
                _tool_call_data("find_service", {"query": "0x0A01"}, "call-1"),
                _tool_call_data(
                    "get_offer_timeline",
                    {"service_id": "0x0A01"},
                    "call-2",
                ),
            ]),
            AIMessage(content="已找到服务，但 Offer 时间线查询失败。"),
        ])

        def handler(name, _arguments, _session_id):
            if name == "get_offer_timeline":
                raise ValueError("测试失败")
            return {"matched_service_count": 1, "services": [{"service_id": "0x0A01"}]}

        result = _graph(main, classifier).invoke(
            {"messages": [{"role": "user", "content": "分析 0x0A01 的 Offer"}]},
            context=_context(handler),
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual([row["status"] for row in result["tool_trace"]], ["success", "failed"])
        self.assertIn("查询限制", result["final_answer"])

    def test_invalid_arguments_can_be_repaired_by_react_model(self):
        classifier = _classifier("service_lookup")
        main = _ScriptedChatModel(responses=[
            _tool_call("find_service", {"query": "Parking", "limit": 999}, "bad"),
            _tool_call("find_service", {"query": "Parking", "limit": 1}, "fixed"),
            AIMessage(content="找到一个 Parking 服务。"),
        ])
        calls = []

        def handler(name, arguments, _session_id):
            calls.append((name, arguments))
            return {"matched_service_count": 1, "services": []}

        result = _graph(main, classifier).invoke(
            {"messages": [{"role": "user", "content": "查找 Parking 服务"}]},
            context=_context(handler),
        )

        self.assertEqual(calls, [("find_service", {"query": "Parking", "limit": 1})])
        self.assertEqual(len(result["tool_trace"]), 2)
        self.assertEqual(result["tool_trace"][0]["error_code"], "invalid_arguments")
        self.assertEqual(result["status"], "completed")

    def test_pre_cancelled_run_never_calls_classifier_or_tool(self):
        classifier = _classifier("general_diagnostic")
        main = _ScriptedChatModel(responses=[])
        cancel_event = Event()
        cancel_event.set()
        context = _context(
            lambda *_args: self.fail("取消请求不应执行 Tool"),
            cancel_event=cancel_event,
        )

        result = _graph(main, classifier).invoke(
            {"messages": [{"role": "user", "content": "总结抓包"}]},
            context=context,
        )

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(classifier.invocation_count, 0)
        self.assertEqual(main.invocation_count, 0)

    def test_compare_without_authorized_sessions_routes_to_clarification(self):
        classifier = _classifier(
            "session_comparison",
            scope="cross_session",
        )
        main = _ScriptedChatModel(responses=[])

        result = _graph(main, classifier).invoke(
            {"messages": [{"role": "user", "content": "比较两个抓包"}]},
            context=_context(lambda *_args: {}),
        )

        self.assertEqual(result["status"], "completed")
        self.assertIn("勾选", result["final_answer"])
        self.assertEqual(result["route"], AgentRoute.FINISH.value)
        self.assertEqual(main.invocation_count, 0)

    def test_model_round_budget_stops_react_loop(self):
        classifier = _classifier("service_lookup")
        main = _ScriptedChatModel(responses=[
            _tool_call("find_service", {"query": "Parking"}, "call-1"),
            AIMessage(content="这一条不应被调用"),
        ])
        budget = ToolExecutionBudget(max_model_rounds=2)
        context = _context(
            lambda *_args: {"matched_service_count": 1, "services": []},
            budget=budget,
        )

        result = _graph(main, classifier).invoke(
            {"messages": [{"role": "user", "content": "查找 Parking 服务"}]},
            context=context,
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("模型调用", result["final_answer"])
        self.assertEqual(context.tool_executor.run_record.model_rounds, 2)

    def test_third_identical_tool_call_is_blocked(self):
        classifier = _classifier("service_lookup")
        same_call = {"query": "Parking", "limit": 1}
        main = _ScriptedChatModel(responses=[
            _tool_call("find_service", same_call, "call-1"),
            _tool_call("find_service", same_call, "call-2"),
            _tool_call("find_service", same_call, "call-3"),
            AIMessage(content="已基于前两次结果回答。"),
        ])
        calls = []

        def handler(name, arguments, _session_id):
            calls.append((name, arguments))
            return {"matched_service_count": 1, "services": []}

        result = _graph(main, classifier).invoke(
            {"messages": [{"role": "user", "content": "反复查找 Parking"}]},
            context=_context(handler),
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(result["tool_trace"][-1]["error_code"], "duplicate_tool_call")
        self.assertIn("查询限制", result["final_answer"])

    def test_context_window_limit_fails_before_model_call(self):
        classifier = _classifier("general_diagnostic")
        context = _context(
            lambda *_args: {},
            model_config=SimpleNamespace(
                configured=True,
                model="test-model",
                context_window=100,
                max_output_tokens=50,
            ),
        )

        result = _graph(_ScriptedChatModel(responses=[]), classifier).invoke(
            {"messages": [{"role": "user", "content": "总结当前抓包"}]},
            context=context,
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("上下文窗口", result["final_answer"])
        self.assertEqual(classifier.invocation_count, 0)

    def test_empty_tool_result_is_preserved_as_successful_fact(self):
        classifier = _classifier("service_lookup")
        main = _ScriptedChatModel(responses=[
            _tool_call("find_service", {"query": "Missing"}, "call-1"),
            AIMessage(content="当前会话没有匹配的服务。"),
        ])
        result = _graph(main, classifier).invoke(
            {"messages": [{"role": "user", "content": "查找 Missing 服务"}]},
            context=_context(
                lambda *_args: {"matched_service_count": 0, "services": []}
            ),
        )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["tool_trace"][0]["empty_result"])
        self.assertTrue(any("未找到匹配数据" in item for item in result["warnings"]))

    def test_unknown_route_is_normalized_to_failed(self):
        self.assertEqual(state_route({"route": "not-a-route"}), AgentRoute.FAILED.value)

    def test_bootstrap_rejects_chat_model_without_tool_calling(self):
        model = GenericFakeChatModel(messages=iter([AIMessage(content="unused")]))
        graph = build_someip_agent_graph(
            model,
            system_prompt="测试",
            classifier_model=_classifier("general_conversation", requires_tools=False),
        )

        result = graph.invoke(
            {"messages": [{"role": "user", "content": "你好"}]},
            context=_context(lambda *_args: {}),
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("Tool Calling", result["final_answer"])


def _graph(main: BaseChatModel, classifier: BaseChatModel):
    return build_someip_agent_graph(
        main,
        system_prompt="你是测试 SOME/IP 诊断助手，只依据 Tool 结果回答。",
        classifier_model=classifier,
    )


def _classifier(
    intent: str,
    *,
    requires_tools: bool = True,
    entities: dict[str, Any] | None = None,
    scope: str = "current_session",
) -> _ScriptedChatModel:
    return _ScriptedChatModel(responses=[AIMessage(
        content="",
        tool_calls=[{
            "name": "IntentClassification",
            "args": {
                "intent": intent,
                "requires_tools": requires_tools,
                "confidence": 0.99,
                "entities": entities or {},
                "needs_clarification": False,
                "clarification_question": None,
                "scope": scope,
            },
            "id": "classification-1",
            "type": "tool_call",
        }],
    )])


def _tool_call(name: str, arguments: dict[str, Any], call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[_tool_call_data(name, arguments, call_id)],
    )


def _tool_call_data(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {
        "name": name,
        "args": arguments,
        "id": call_id,
        "type": "tool_call",
    }


def _context(handler, *, cancel_event=None, budget=None, model_config=None):
    record = AssistantRunRecord(
        request_id="graph-test",
        session_id="capture-a",
        model="test-model",
        prompt_version="test",
        answer_contract_version="test",
    )
    return create_tool_context(
        "capture-a",
        record,
        cancel_event=cancel_event,
        budget=budget,
        model_config=model_config,
        tool_handler=handler,
    )


if __name__ == "__main__":
    unittest.main()
