"""AI Tool registry.

Each concrete Tool lives in its own module. This package only exposes model
schemas and dispatches calls through an explicit read-only allowlist.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .subscription_status import TOOL_DEFINITION as SUBSCRIPTION_STATUS_DEFINITION
from .subscription_status import get_subscription_status

ToolHandler = Callable[[str, dict[str, Any]], dict[str, Any]]


def _run_subscription_status(
    session_id: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    return get_subscription_status(session_id, arguments.get("service_id"))


TOOL_DEFINITIONS: list[dict[str, Any]] = [SUBSCRIPTION_STATUS_DEFINITION]

_TOOL_HANDLERS: dict[str, ToolHandler] = {
    "get_subscription_status": _run_subscription_status,
}


def execute_tool(name: str, arguments: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Execute a registered Tool against the server-injected parse session."""
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"未知工具: {name}")
    return handler(session_id, arguments)


def tool_result_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


__all__ = [
    "TOOL_DEFINITIONS",
    "execute_tool",
    "get_subscription_status",
    "tool_result_json",
]
