"""SOME/IP Agent 的可序列化 LangGraph State。"""
from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import NotRequired, TypedDict


class SomeIpAgentState(TypedDict):
    """LangGraph 节点之间共享的状态。

    ``messages`` 使用 LangGraph reducer 追加消息。Tool 原始结果只存在 ToolMessage
    artifact；``evidence`` 和 ``tool_trace`` 保存可审计的有限结构，后续节点无需从
    模型自然语言中反向恢复事实。
    """

    messages: Annotated[list[AnyMessage], add_messages]
    question: NotRequired[str]
    intent: NotRequired[dict[str, Any]]
    entities: NotRequired[dict[str, Any]]
    route: NotRequired[str]
    selected_tools: NotRequired[list[str]]
    react_messages: NotRequired[list[AnyMessage]]
    tool_trace: NotRequired[list[dict[str, Any]]]
    evidence: NotRequired[list[dict[str, Any]]]
    navigation_links: NotRequired[list[dict[str, Any]]]
    draft_answer: NotRequired[str]
    reflection: NotRequired[dict[str, Any] | None]
    final_answer: NotRequired[str]
    budget: NotRequired[dict[str, int | float]]
    warnings: NotRequired[list[str]]
    status: NotRequired[str]
    error: NotRequired[str | None]
    metadata: NotRequired[dict[str, Any]]


__all__ = ["SomeIpAgentState"]
