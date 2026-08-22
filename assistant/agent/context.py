"""LangGraph 单次运行所需、但不应写入模型消息的依赖。"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Any

from ..execution.tool_executor import ToolExecutor


@dataclass(frozen=True)
class SomeIpAgentContext:
    """通过 LangGraph Runtime 注入的请求级依赖。

    查询对象、取消信号和授权会话不能进入 Graph State，否则 Checkpoint 可能
    序列化进程内对象或敏感权限信息。第一阶段先固定这个边界，后续节点直接复用。
    """

    session_id: str
    allowed_session_ids: frozenset[str] = frozenset()
    session_queries: Any = None
    cancel_event: Event | None = None
    tool_executor: ToolExecutor | None = None


__all__ = ["SomeIpAgentContext"]
