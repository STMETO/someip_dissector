"""Agent 条件边使用的稳定路由名称。"""
from __future__ import annotations

from enum import Enum


class AgentRoute(str, Enum):
    """后续 Graph 节点共同使用的有限状态，禁止用任意字符串分支。"""

    DIRECT_ANSWER = "direct_answer"
    USE_TOOLS = "use_tools"
    CLARIFY = "clarify"
    PARTIAL_FAILURE = "partial_failure"
    CANCELLED = "cancelled"
    FAILED = "failed"
    FINISH = "finish"


__all__ = ["AgentRoute"]
