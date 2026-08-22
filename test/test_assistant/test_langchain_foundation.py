"""第一阶段 LangChain/LangGraph 基础设施测试。"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any
import unittest

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, PrivateAttr

from assistant.agent import build_model_smoke_graph
from assistant.integrations.langchain import (
    ModelCapabilityError,
    ModelFactoryError,
    create_chat_model,
    resolve_chat_model_provider,
)
from assistant.llm.config import ModelConfig


class _ProbeResult(BaseModel):
    """验证 Structured Output 能返回真实 Pydantic 对象。"""

    answer: str


class _ScriptedChatModel(BaseChatModel):
    """不访问网络的标准 ChatModel，用脚本消息模拟 Tool Calling。"""

    responses: list[AIMessage]
    _bound_tools: list[Any] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "someip-scripted-test"

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
        # BaseChatModel.with_structured_output 与 create_agent 都通过此方法绑定工具。
        self._bound_tools = list(tools)
        return self


@tool
def _increment(value: int) -> int:
    """将测试整数加一。"""
    return value + 1


class LangChainFoundationTests(unittest.TestCase):
    """验证第一阶段引入的模型、图和标准协议。"""

    def test_provider_resolution_and_official_chat_models(self):
        deepseek = create_chat_model(
            _config("auto", "https://api.deepseek.com", "deepseek-chat"),
            require_tools=True,
        )
        generic = create_chat_model(
            _config("openai_compatible", "https://llm.example.com/v1", "test-model"),
            require_tools=True,
            overrides={"max_retries": 0},
        )

        self.assertIsInstance(deepseek, ChatDeepSeek)
        self.assertEqual(deepseek.model_name, "deepseek-chat")
        self.assertEqual(deepseek.max_tokens, 4096)
        self.assertIsInstance(generic, ChatOpenAI)
        self.assertEqual(generic.model_name, "test-model")
        self.assertEqual(generic.openai_api_base, "https://llm.example.com/v1")
        self.assertEqual(generic.max_retries, 0)

    def test_provider_resolution_rejects_unknown_provider(self):
        config = _config("unknown", "https://llm.example.com/v1", "test-model")

        with self.assertRaisesRegex(ModelFactoryError, "不支持的模型 Provider"):
            resolve_chat_model_provider(config)

    def test_reasoner_is_rejected_when_tool_calling_is_required(self):
        config = _config("deepseek", "https://api.deepseek.com", "deepseek-reasoner")

        with self.assertRaisesRegex(ModelCapabilityError, "不支持.*Tool Calling"):
            create_chat_model(config, require_tools=True)

    def test_minimal_langgraph_appends_model_message(self):
        model = GenericFakeChatModel(messages=iter([AIMessage(content="基础图正常")]))
        graph = build_model_smoke_graph(model)

        result = graph.invoke({"messages": [{"role": "user", "content": "测试"}]})

        self.assertEqual(result["status"], "completed")
        self.assertEqual([message.type for message in result["messages"]], ["human", "ai"])
        self.assertEqual(result["messages"][-1].content, "基础图正常")

    def test_standard_chat_model_can_stream(self):
        model = GenericFakeChatModel(messages=iter([AIMessage(content="流式回答")]))

        content = "".join(str(chunk.content) for chunk in model.stream("测试流式"))

        self.assertEqual(content, "流式回答")

    def test_standard_chat_model_supports_pydantic_structured_output(self):
        model = _ScriptedChatModel(responses=[AIMessage(
            content="",
            tool_calls=[{
                "name": "_ProbeResult",
                "args": {"answer": "结构化结果"},
                "id": "structured-1",
                "type": "tool_call",
            }],
        )])

        result = model.with_structured_output(_ProbeResult).invoke("返回结构化结果")

        self.assertIsInstance(result, _ProbeResult)
        self.assertEqual(result.answer, "结构化结果")

    def test_create_agent_executes_simulated_tool_call(self):
        model = _ScriptedChatModel(responses=[
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "_increment",
                    "args": {"value": 41},
                    "id": "tool-1",
                    "type": "tool_call",
                }],
            ),
            AIMessage(content="工具结果是 42"),
        ])
        agent = create_agent(model=model, tools=[_increment])

        result = agent.invoke({"messages": [{"role": "user", "content": "41 加一"}]})

        self.assertEqual(result["messages"][-1].content, "工具结果是 42")
        tool_messages = [item for item in result["messages"] if item.type == "tool"]
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(tool_messages[0].content, "42")


def _config(provider: str, api_base: str, model: str) -> ModelConfig:
    """构造不访问网络的模型配置。"""
    return ModelConfig(
        api_key="test-key",
        api_base=api_base,
        model=model,
        timeout_seconds=5.0,
        source="test",
        provider=provider,
    )


if __name__ == "__main__":
    unittest.main()
