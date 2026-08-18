"""查询 SOME/IP-SD 订阅诊断总览的 Tool。"""
from __future__ import annotations

from typing import Any

from assistant.tool_support import format_hex, parse_int, require_queries

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_subscription_status",
        "description": (
            "查询当前 PCAP 的 SOME/IP-SD Offer、Subscribe、Ack、Nack 和 "
            "Notification 诊断总览。适合回答整体状态或指定服务的订阅健康情况。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "string",
                    "description": "可选 Service ID，例如 0x1234；为空时返回全部服务。",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}

_METRIC_DEFINITIONS = {
    "service_count": "抓包中观察到 Offer 或 Subscribe 的服务数量",
    "offered_service_count": "观察到至少一条有效 Offer 的服务数量",
    "observed_subscription_eventgroup_count": "观察到 Subscribe 的 EventGroup 数量",
    "offer_conflict_service_count": "同一 Service ID 和 Instance ID 由多个源 ECU 发布 Offer 的服务数量",
    "subscribed_without_notification_eventgroup_count": "已 Subscribe 且已 Ack，但订阅后没有 Notification 的 EventGroup 数量",
    "offered_without_subscriber_service_count": "已 Offer 但没有任何客户端 Subscribe 的服务数量",
    "subscribed_without_offer_service_count": "存在 Subscribe 但没有观察到 Offer 的服务数量",
    "subscribed_without_ack_eventgroup_count": "已 Subscribe 但没有观察到 Ack 的 EventGroup 数量",
    "nacked_eventgroup_count": "观察到 Subscribe Nack 的 EventGroup 数量",
}


def get_subscription_status(session_id: str, service_id: Any = None) -> dict[str, Any]:
    """返回统计单位明确、带报文证据的订阅诊断结果。"""
    state, queries = require_queries(session_id)
    # 诊断页和 AI 共用会话构建时生成的报告，避免重复扫描完整抓包。
    report = queries.subscriptions.report()
    requested_id = parse_int(service_id, "Service ID")
    services = report.get("services", [])
    if requested_id is not None:
        services = [row for row in services if row.get("service_id") == requested_id]

    compact = [_compact_service(row) for row in services[:50]]
    result: dict[str, Any] = {
        "capture": {
            "pcap_name": state.pcap_name,
            "message_count": state.total_messages or len(state.messages),
        },
        "summary": report.get("summary", {}),
        "metric_definitions": _METRIC_DEFINITIONS,
        "service_filter": format_hex(requested_id) if requested_id is not None else None,
        "matched_service_count": len(services),
        "services": compact,
        "truncated": len(services) > len(compact),
        "fact_scope": "仅描述当前抓包中实际观察到的报文，不代表抓包时间范围外的状态",
    }
    if requested_id is not None and not services:
        result["available_services"] = [
            row.get("service_id_hex") for row in report.get("services", [])[:50]
        ]
    return result


def _compact_service(service: dict[str, Any]) -> dict[str, Any]:
    """压缩重复周期报文，同时保留首尾证据和真实计数。"""
    return {
        "service_id": service.get("service_id_hex"),
        "service_name": service.get("service_name") or None,
        "offer_observed": bool(service.get("has_offer")),
        "offer_count": int(service.get("offer_count", 0)),
        "server_ecus": service.get("server_ecus", []),
        "instance_ids": [format_hex(value) for value in service.get("instance_ids", [])],
        "offer_instances": [
            {
                "instance_id": format_hex(int(instance.get("instance_id", 0))),
                "server_ecus": instance.get("server_ecus", []),
                "offer_count": int(instance.get("offer_count", 0)),
                "offer_conflict": bool(instance.get("offer_conflict")),
                "offer_evidence": _limit_evidence(
                    instance.get("offer_evidence", []), 4
                ),
            }
            for instance in service.get("offer_instances", [])
        ],
        "offer_conflict": bool(service.get("offer_conflict")),
        "offer_conflict_instance_ids": [
            format_hex(value) for value in service.get("offer_conflict_instance_ids", [])
        ],
        "offer_evidence": _limit_evidence(service.get("offer_evidence", []), 6),
        "issues": service.get("issues", []),
        "eventgroups": [
            {
                "eventgroup_id": format_hex(int(eg.get("eventgroup_id", 0))),
                "eventgroup_name": eg.get("eventgroup_name") or None,
                "event_name": eg.get("event_name") or None,
                "clients": eg.get("client_ecus", []),
                "subscribed": bool(eg.get("subscribed")),
                "subscribe_count": int(eg.get("subscribe_count", 0)),
                "acknowledged": bool(eg.get("acked")),
                "ack_count": int(eg.get("ack_count", 0)),
                "nacked": bool(eg.get("nacked")),
                "nack_count": int(eg.get("nack_count", 0)),
                "ack_ecus": eg.get("ack_ecus", []),
                "nack_ecus": eg.get("nack_ecus", []),
                "notification_count": int(eg.get("notification_count", 0)),
                "subscribe_evidence": _limit_evidence(eg.get("subscribe_evidence", []), 4),
                "ack_evidence": _limit_evidence(eg.get("ack_evidence", []), 4),
                "nack_evidence": _limit_evidence(eg.get("nack_evidence", []), 4),
                "notification_evidence": _limit_evidence(
                    eg.get("notification_evidence", []), 4
                ),
                "issues": eg.get("issues", []),
            }
            for eg in service.get("eventgroups", [])[:40]
        ],
    }


def _limit_evidence(evidence: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """总览只保留首尾证据，完整时间序列由专用 Timeline Tool 查询。"""
    if len(evidence) <= limit:
        return evidence
    head = limit // 2
    return evidence[:head] + evidence[-(limit - head):]


__all__ = ["TOOL_DEFINITION", "get_subscription_status"]
