"""AI 助手测试使用的标准 LangChain 假模型。"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr


class ScriptedChatModel(BaseChatModel):
    """按脚本返回标准 AIMessage，覆盖 Structured Output 与 Tool Calling。"""

    responses: list[AIMessage]
    _bound_tools: list[Any] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "someip-service-scripted-test"

    def _generate(self, _messages, stop=None, run_manager=None, **_kwargs) -> ChatResult:
        del stop, run_manager
        if not self.responses:
            raise AssertionError("测试模型没有剩余响应")
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])

    def bind_tools(self, tools: Sequence[Any], **_kwargs) -> "ScriptedChatModel":
        self._bound_tools = list(tools)
        return self


class FailingChatModel(ScriptedChatModel):
    """模拟所有模型节点都无法连接上游。"""

    def _generate(self, _messages, stop=None, run_manager=None, **_kwargs) -> ChatResult:
        del stop, run_manager
        raise RuntimeError("上游连接失败")


def classification_message(
    intent: str,
    *,
    requires_tools: bool = True,
    complexity: str = "simple",
    answer_kind: str = "lookup",
) -> AIMessage:
    """构造 IntentClassification 的标准 Structured Output Tool Call。"""
    return AIMessage(content="", tool_calls=[{
        "name": "IntentClassification",
        "args": {
            "intent": intent,
            "requires_tools": requires_tools,
            "confidence": 0.99,
            "entities": {},
            "needs_clarification": False,
            "clarification_question": None,
            "scope": "current_session",
            "complexity": complexity,
            "answer_kind": answer_kind,
        },
        "id": "classification-1",
        "type": "tool_call",
    }])


def tool_call_message(
    name: str,
    arguments: dict[str, Any],
    call_id: str,
) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[tool_call_data(name, arguments, call_id)],
    )


def tool_call_data(
    name: str,
    arguments: dict[str, Any],
    call_id: str,
) -> dict[str, Any]:
    return {"name": name, "args": arguments, "id": call_id, "type": "tool_call"}


__all__ = [
    "FailingChatModel",
    "ScriptedChatModel",
    "classification_message",
    "tool_call_data",
    "tool_call_message",
]
