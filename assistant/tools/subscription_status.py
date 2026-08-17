"""Tool for querying SOME/IP-SD subscription diagnostics."""
from __future__ import annotations

from typing import Any

from web.backend.handlers.sd_diagnostic import get_subscription_report

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_subscription_status",
        "description": (
            "查询当前 PCAP 会话中的 SOME/IP-SD Offer、Subscribe、Ack 和 "
            "Notification 诊断结果。用户询问服务发布或订阅状态时必须调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "string",
                    "description": (
                        "可选的 Service ID，推荐使用 0x1234 形式；为空时返回整个抓包概览。"
                    ),
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


def get_subscription_status(session_id: str, service_id: Any = None) -> dict[str, Any]:
    """Return a compact model-friendly view of the existing SD report."""
    report = get_subscription_report(session_id)
    if report is None:
        raise ValueError("解析会话不存在或已过期")

    requested_id = _parse_service_id(service_id)
    services = report.get("services", [])
    if requested_id is not None:
        services = [row for row in services if row.get("service_id") == requested_id]

    compact = [_compact_service(row) for row in services[:50]]
    result: dict[str, Any] = {
        "summary": report.get("summary", {}),
        "service_filter": f"0x{requested_id:04X}" if requested_id is not None else None,
        "matched_service_count": len(services),
        "services": compact,
        "truncated": len(services) > len(compact),
    }
    if requested_id is not None and not services:
        result["available_services"] = [
            row.get("service_id_hex") for row in report.get("services", [])[:50]
        ]
    return result


def _compact_service(service: dict[str, Any]) -> dict[str, Any]:
    return {
        "service_id": service.get("service_id_hex"),
        "service_name": service.get("service_name") or None,
        "offered": bool(service.get("has_offer")),
        "server_ecus": service.get("server_ecus", []),
        "offer_conflict": bool(service.get("offer_conflict")),
        "issues": service.get("issues", []),
        "eventgroups": [
            {
                "eventgroup_id": f"0x{int(eg.get('eventgroup_id', 0)):04X}",
                "eventgroup_name": eg.get("eventgroup_name") or None,
                "event_name": eg.get("event_name") or None,
                "clients": eg.get("client_ecus", []),
                "acknowledged": bool(eg.get("acked")),
                "ack_ecus": eg.get("ack_ecus", []),
                "notification_count": int(eg.get("notification_count", 0)),
                "issues": eg.get("issues", []),
            }
            for eg in service.get("eventgroups", [])[:40]
        ],
    }


def _parse_service_id(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("Service ID 格式错误")
    try:
        parsed = int(str(value).strip(), 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Service ID 应为 0x1234 或十进制整数") from exc
    if not 0 <= parsed <= 0xFFFF:
        raise ValueError("Service ID 必须在 0x0000 到 0xFFFF 之间")
    return parsed


__all__ = ["TOOL_DEFINITION", "get_subscription_status"]
