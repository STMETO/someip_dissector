"""展开订阅诊断异常详情的 Tool。"""
from __future__ import annotations

from typing import Any

from .support import clamp_limit, parse_int, parse_text, require_queries

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_anomaly_details",
        "description": (
            "按异常类型展开受影响的 Service、Instance、EventGroup、客户端和代表报文证据。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "anomaly_type": {
                    "type": "string",
                    "description": (
                        "默认 all；可选 offer_conflict、offered_without_subscription、"
                        "subscribed_without_offer、subscribed_without_ack、nacked、"
                        "subscribed_without_notification。"
                    ),
                },
                "service_id": {"type": "string", "description": "可选 Service ID。"},
                "offset": {"type": "integer", "description": "分页偏移，默认 0。"},
                "limit": {"type": "integer", "description": "返回数量，默认 80，最大 200。"},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


def get_anomaly_details(
    session_id: str,
    anomaly_type: Any = None,
    service_id: Any = None,
    offset: Any = None,
    limit: Any = None,
) -> dict[str, Any]:
    """从已缓存的订阅报告读取异常，不重复构建诊断结果。"""
    _, queries = require_queries(session_id)
    return queries.anomalies.query(
        anomaly_type=parse_text(anomaly_type, "anomaly_type", max_length=64) or "all",
        service_id=parse_int(service_id, "Service ID"),
        offset=int(parse_int(offset, "offset", minimum=0, maximum=10_000_000) or 0),
        limit=clamp_limit(limit, default=80, maximum=200),
    )


__all__ = ["TOOL_DEFINITION", "get_anomaly_details"]
