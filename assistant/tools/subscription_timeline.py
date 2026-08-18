"""查询 SOME/IP-SD 订阅生命周期时间线的 Tool。"""
from __future__ import annotations

from typing import Any

from assistant.tool_support import (
    clamp_limit,
    parse_float,
    parse_int,
    require_queries,
)

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_subscription_timeline",
        "description": (
            "查询指定服务的 Subscribe、StopSubscribe、Ack、Nack 和关联的 "
            "Notification 时间线，可继续按 EventGroup、Instance 或客户端过滤。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service_id": {"type": "string", "description": "必填 Service ID，例如 0x0A01。"},
                "eventgroup_id": {"type": "string", "description": "可选 EventGroup ID。"},
                "instance_id": {"type": "string", "description": "可选 Instance ID。"},
                "client_ip": {"type": "string", "description": "可选订阅客户端 IP。"},
                "start_time": {"type": "number", "description": "可选起始 epoch 秒。"},
                "end_time": {"type": "number", "description": "可选结束 epoch 秒。"},
                "offset": {"type": "integer", "description": "分页偏移，默认 0。"},
                "limit": {"type": "integer", "description": "返回数量，默认 80，最大 200。"},
            },
            "required": ["service_id"],
            "additionalProperties": False,
        },
    },
}


def get_subscription_timeline(
    session_id: str,
    service_id: Any,
    eventgroup_id: Any = None,
    instance_id: Any = None,
    client_ip: Any = None,
    start_time: Any = None,
    end_time: Any = None,
    offset: Any = None,
    limit: Any = None,
) -> dict[str, Any]:
    """校验模型参数，并转发到页面和 AI 共用的订阅查询对象。"""
    _, queries = require_queries(session_id)
    sid = int(parse_int(service_id, "Service ID", required=True))
    eventgroup = parse_int(eventgroup_id, "EventGroup ID")
    instance = parse_int(instance_id, "Instance ID")
    client = str(client_ip or "").strip() or None
    start = parse_float(start_time, "start_time")
    end = parse_float(end_time, "end_time")
    page_offset = int(
        parse_int(offset, "offset", minimum=0, maximum=10_000_000) or 0
    )
    page_limit = clamp_limit(limit, default=80, maximum=200)
    return queries.subscriptions.timeline(
        sid,
        eventgroup_id=eventgroup,
        instance_id=instance,
        client_ip=client,
        start_time=start,
        end_time=end,
        offset=page_offset,
        limit=page_limit,
    )


__all__ = ["TOOL_DEFINITION", "get_subscription_timeline"]
