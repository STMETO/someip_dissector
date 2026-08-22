"""LangGraph 单次运行所需、但不进入模型消息的依赖。"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Any

from ...execution.tool_executor import ToolExecutor


@dataclass(frozen=True)
class SomeIpAgentContext:
    """通过 LangGraph Runtime 注入的请求级依赖。

    取消信号、授权会话和 ToolExecutor 不能写入 Graph State，避免 Checkpoint
    序列化进程对象、权限信息或运行时密钥。
    """

    session_id: str
    allowed_session_ids: frozenset[str] = frozenset()
    session_queries: Any = None
    model_config: Any = None
    cancel_event: Event | None = None
    tool_executor: ToolExecutor | None = None


__all__ = ["SomeIpAgentContext"]
