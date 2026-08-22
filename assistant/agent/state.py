"""SOME/IP Agent 的最小可序列化状态定义。"""
from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import NotRequired, TypedDict


class SomeIpAgentState(TypedDict):
    """LangGraph 节点之间共享的状态。

    ``messages`` 使用 LangGraph 的 reducer 追加消息，避免节点覆盖历史。其余字段
    会在后续 ReAct 与 Reflection 阶段扩展，目前只保留基础图可运行的最小集合。
    """

    messages: Annotated[list[AnyMessage], add_messages]
    status: NotRequired[str]
    error: NotRequired[str | None]
    metadata: NotRequired[dict[str, Any]]


__all__ = ["SomeIpAgentState"]
