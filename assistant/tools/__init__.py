"""AI Tool 注册表。

每个具体 Tool 独占一个模块。本文件只负责导出模型 Schema，并通过显式的
只读白名单分发调用，模型无法执行未注册的任意函数。
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .find_service import TOOL_DEFINITION as FIND_SERVICE_DEFINITION
from .find_service import find_service
from .message_detail import TOOL_DEFINITION as MESSAGE_DETAIL_DEFINITION
from .message_detail import get_message_detail
from .offer_timeline import TOOL_DEFINITION as OFFER_TIMELINE_DEFINITION
from .offer_timeline import get_offer_timeline
from .search_messages import TOOL_DEFINITION as SEARCH_MESSAGES_DEFINITION
from .search_messages import search_messages
from .subscription_status import TOOL_DEFINITION as SUBSCRIPTION_STATUS_DEFINITION
from .subscription_status import get_subscription_status
from .subscription_timeline import TOOL_DEFINITION as SUBSCRIPTION_TIMELINE_DEFINITION
from .subscription_timeline import get_subscription_timeline

ToolHandler = Callable[[str, dict[str, Any]], dict[str, Any]]


def _run_subscription_status(
    session_id: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    return get_subscription_status(session_id, arguments.get("service_id"))


def _run_find_service(session_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return find_service(session_id, arguments.get("query"), arguments.get("limit"))


def _run_offer_timeline(session_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return get_offer_timeline(
        session_id,
        arguments.get("service_id"),
        arguments.get("instance_id"),
        arguments.get("start_time"),
        arguments.get("end_time"),
        arguments.get("offset"),
        arguments.get("limit"),
    )


def _run_subscription_timeline(
    session_id: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    return get_subscription_timeline(
        session_id,
        arguments.get("service_id"),
        arguments.get("eventgroup_id"),
        arguments.get("instance_id"),
        arguments.get("client_ip"),
        arguments.get("start_time"),
        arguments.get("end_time"),
        arguments.get("offset"),
        arguments.get("limit"),
    )


def _run_search_messages(session_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return search_messages(
        session_id,
        arguments.get("service_id"),
        arguments.get("method_id"),
        arguments.get("message_type"),
        arguments.get("src_ip"),
        arguments.get("dst_ip"),
        arguments.get("sd_entry_type"),
        arguments.get("parse_status"),
        arguments.get("start_time"),
        arguments.get("end_time"),
        arguments.get("offset"),
        arguments.get("limit"),
    )


def _run_message_detail(session_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return get_message_detail(
        session_id,
        arguments.get("message_index"),
        arguments.get("include_payload_hex", False),
        arguments.get("include_parsed_tree", True),
    )


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    SUBSCRIPTION_STATUS_DEFINITION,
    FIND_SERVICE_DEFINITION,
    OFFER_TIMELINE_DEFINITION,
    SUBSCRIPTION_TIMELINE_DEFINITION,
    SEARCH_MESSAGES_DEFINITION,
    MESSAGE_DETAIL_DEFINITION,
]

_TOOL_HANDLERS: dict[str, ToolHandler] = {
    "get_subscription_status": _run_subscription_status,
    "find_service": _run_find_service,
    "get_offer_timeline": _run_offer_timeline,
    "get_subscription_timeline": _run_subscription_timeline,
    "search_messages": _run_search_messages,
    "get_message_detail": _run_message_detail,
}


def execute_tool(name: str, arguments: dict[str, Any], session_id: str) -> dict[str, Any]:
    """在服务端注入的解析会话上执行已注册 Tool。"""
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"未知工具: {name}")
    return handler(session_id, arguments)


def tool_result_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


__all__ = [
    "TOOL_DEFINITIONS",
    "execute_tool",
    "find_service",
    "get_message_detail",
    "get_offer_timeline",
    "get_subscription_status",
    "get_subscription_timeline",
    "search_messages",
    "tool_result_json",
]
