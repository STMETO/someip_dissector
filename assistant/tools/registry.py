"""AI Tool 注册表。

每个具体 Tool 独占一个模块。本文件只负责导出模型 Schema，并通过显式的
只读白名单分发调用，模型无法执行未注册的任意函数。
"""
from __future__ import annotations

import json
from typing import Any, Callable, Iterable

from .anomaly_details import TOOL_DEFINITION as ANOMALY_DETAILS_DEFINITION
from .anomaly_details import get_anomaly_details
from .arxml_definition import TOOL_DEFINITION as ARXML_DEFINITION_DEFINITION
from .arxml_definition import get_arxml_definition
from .compare_sessions import TOOL_DEFINITION as COMPARE_SESSIONS_DEFINITION
from .compare_sessions import compare_sessions
from .ecu_service_topology import TOOL_DEFINITION as ECU_TOPOLOGY_DEFINITION
from .ecu_service_topology import get_ecu_service_topology
from .find_service import TOOL_DEFINITION as FIND_SERVICE_DEFINITION
from .find_service import find_service
from .message_detail import TOOL_DEFINITION as MESSAGE_DETAIL_DEFINITION
from .message_detail import get_message_detail
from .notification_statistics import (
    TOOL_DEFINITION as NOTIFICATION_STATISTICS_DEFINITION,
)
from .notification_statistics import get_notification_statistics
from .offer_timeline import TOOL_DEFINITION as OFFER_TIMELINE_DEFINITION
from .offer_timeline import get_offer_timeline
from .payload_field import TOOL_DEFINITION as PAYLOAD_FIELD_DEFINITION
from .payload_field import get_payload_field
from .payload_value_search import TOOL_DEFINITION as PAYLOAD_VALUE_SEARCH_DEFINITION
from .payload_value_search import search_payload_values
from .request_response_trace import TOOL_DEFINITION as REQUEST_RESPONSE_DEFINITION
from .request_response_trace import get_request_response_trace
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


def _run_notification_statistics(
    session_id: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    return get_notification_statistics(
        session_id,
        arguments.get("service_id"),
        arguments.get("method_id"),
        arguments.get("field_path"),
        arguments.get("start_time"),
        arguments.get("end_time"),
    )


def _run_payload_field(session_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return get_payload_field(
        session_id,
        arguments.get("message_index"),
        arguments.get("field_path"),
    )


def _run_request_response_trace(
    session_id: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    return get_request_response_trace(
        session_id,
        arguments.get("service_id"),
        arguments.get("method_id"),
        arguments.get("client_id"),
        arguments.get("session_id"),
        arguments.get("status"),
        arguments.get("start_time"),
        arguments.get("end_time"),
        arguments.get("offset"),
        arguments.get("limit"),
    )


def _run_ecu_topology(session_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return get_ecu_service_topology(
        session_id,
        arguments.get("ecu_ip"),
        arguments.get("service_id"),
        arguments.get("limit"),
    )


def _run_arxml_definition(session_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return get_arxml_definition(
        session_id,
        arguments.get("service_id"),
        arguments.get("member_kind"),
        arguments.get("member_id"),
        arguments.get("field_path"),
    )


def _run_payload_value_search(
    session_id: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    return search_payload_values(
        session_id,
        arguments.get("field_path"),
        arguments.get("service_id"),
        arguments.get("method_id"),
        arguments.get("exact_value"),
        arguments.get("text_contains"),
        arguments.get("minimum"),
        arguments.get("maximum"),
        arguments.get("start_time"),
        arguments.get("end_time"),
        arguments.get("offset"),
        arguments.get("limit"),
    )


def _run_anomaly_details(session_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return get_anomaly_details(
        session_id,
        arguments.get("anomaly_type"),
        arguments.get("service_id"),
        arguments.get("offset"),
        arguments.get("limit"),
    )


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    SUBSCRIPTION_STATUS_DEFINITION,
    FIND_SERVICE_DEFINITION,
    OFFER_TIMELINE_DEFINITION,
    SUBSCRIPTION_TIMELINE_DEFINITION,
    SEARCH_MESSAGES_DEFINITION,
    MESSAGE_DETAIL_DEFINITION,
    NOTIFICATION_STATISTICS_DEFINITION,
    PAYLOAD_FIELD_DEFINITION,
    REQUEST_RESPONSE_DEFINITION,
    ECU_TOPOLOGY_DEFINITION,
    ARXML_DEFINITION_DEFINITION,
    PAYLOAD_VALUE_SEARCH_DEFINITION,
    ANOMALY_DETAILS_DEFINITION,
    COMPARE_SESSIONS_DEFINITION,
]

_TOOL_HANDLERS: dict[str, ToolHandler] = {
    "get_subscription_status": _run_subscription_status,
    "find_service": _run_find_service,
    "get_offer_timeline": _run_offer_timeline,
    "get_subscription_timeline": _run_subscription_timeline,
    "search_messages": _run_search_messages,
    "get_message_detail": _run_message_detail,
    "get_notification_statistics": _run_notification_statistics,
    "get_payload_field": _run_payload_field,
    "get_request_response_trace": _run_request_response_trace,
    "get_ecu_service_topology": _run_ecu_topology,
    "get_arxml_definition": _run_arxml_definition,
    "search_payload_values": _run_payload_value_search,
    "get_anomaly_details": _run_anomaly_details,
}


def execute_tool(
    name: str,
    arguments: dict[str, Any],
    session_id: str,
    allowed_session_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """在服务端注入的解析会话上执行已注册 Tool。

    ``compare_sessions`` 额外接收本轮请求白名单；其他 Tool 永远绑定当前会话。
    """
    if name == "compare_sessions":
        return compare_sessions(
            session_id,
            arguments.get("session_ids"),
            allowed_session_ids,
        )
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"未知工具: {name}")
    return handler(session_id, arguments)


def tool_result_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


__all__ = [
    "TOOL_DEFINITIONS",
    "execute_tool",
    "compare_sessions",
    "get_anomaly_details",
    "get_arxml_definition",
    "get_ecu_service_topology",
    "find_service",
    "get_message_detail",
    "get_notification_statistics",
    "get_offer_timeline",
    "get_subscription_status",
    "get_subscription_timeline",
    "get_payload_field",
    "get_request_response_trace",
    "search_messages",
    "search_payload_values",
    "tool_result_json",
]
