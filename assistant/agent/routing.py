"""Agent 条件边使用的稳定路由名称。"""
from __future__ import annotations

from enum import Enum
from typing import Any


class AgentRoute(str, Enum):
    """后续 Graph 节点共同使用的有限状态，禁止用任意字符串分支。"""

    DIRECT_ANSWER = "direct_answer"
    USE_TOOLS = "use_tools"
    CLARIFY = "clarify"
    PARTIAL_FAILURE = "partial_failure"
    REFLECT = "reflect"
    REVISE = "revise"
    CANCELLED = "cancelled"
    FAILED = "failed"
    FINISH = "finish"


def state_route(state: dict[str, Any]) -> str:
    """读取有限路由值，非法值统一进入 failed，避免 Graph 无目标异常。"""
    value = str(state.get("route") or AgentRoute.FAILED.value)
    allowed = {route.value for route in AgentRoute}
    return value if value in allowed else AgentRoute.FAILED.value


__all__ = ["AgentRoute", "state_route"]
