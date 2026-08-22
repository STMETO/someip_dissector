"""Agent 节点共享的消息与运行时辅助函数。"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from ...integrations.langchain.runtime import SomeIpAgentContext


def require_context(runtime: Any) -> SomeIpAgentContext:
    """读取并校验 LangGraph Runtime Context。"""
    context = getattr(runtime, "context", None)
    if not isinstance(context, SomeIpAgentContext):
        raise RuntimeError("LangGraph Runtime 缺少 SomeIpAgentContext")
    return context


def latest_user_question(messages: list[AnyMessage]) -> str:
    """从消息历史中读取最后一个非空用户问题。"""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            value = message_text(message).strip()
            if value:
                return value
    return ""


def latest_ai_text(messages: list[AnyMessage]) -> str:
    """读取最后一条有文本的 AIMessage，跳过纯 Tool Call 消息。"""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            value = message_text(message).strip()
            if value:
                return value
    return ""


def message_text(message: Any) -> str:
    """兼容字符串和标准内容块两种 LangChain 消息格式。"""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            text = item.get("text") or item.get("content")
            if text:
                parts.append(str(text))
    return "".join(parts)


__all__ = [
    "latest_ai_text",
    "latest_user_question",
    "message_text",
    "require_context",
]
