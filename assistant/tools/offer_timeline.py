"""查询服务 Offer 生命周期时间线的 AI Tool。"""
from __future__ import annotations

from typing import Any

from .support import (
    clamp_limit,
    parse_float,
    parse_int,
    require_queries,
)

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_offer_timeline",
        "description": "查询指定服务的 Offer、StopOffer、发布 ECU、TTL 和时间顺序。",
        "parameters": {
            "type": "object",
            "properties": {
                "service_id": {"type": "string", "description": "必填 Service ID，例如 0x0A01。"},
                "instance_id": {"type": "string", "description": "可选 Instance ID。"},
                "start_time": {"type": "number", "description": "可选起始 epoch 秒。"},
                "end_time": {"type": "number", "description": "可选结束 epoch 秒。"},
                "offset": {"type": "integer", "description": "分页偏移，默认 0。"},
                "limit": {"type": "integer", "description": "返回数量，默认 50，最大 200。"},
            },
            "required": ["service_id"],
            "additionalProperties": False,
        },
    },
}


def get_offer_timeline(
    session_id: str,
    service_id: Any,
    instance_id: Any = None,
    start_time: Any = None,
    end_time: Any = None,
    offset: Any = None,
    limit: Any = None,
) -> dict[str, Any]:
    """校验参数后从会话 Offer 索引读取时间线。"""
    _, queries = require_queries(session_id)
    sid = int(parse_int(service_id, "Service ID", required=True))
    iid = parse_int(instance_id, "Instance ID")
    start = parse_float(start_time, "start_time")
    end = parse_float(end_time, "end_time")
    page_offset = int(parse_int(offset, "offset", minimum=0, maximum=10_000_000) or 0)
    page_limit = clamp_limit(limit, default=50, maximum=200)
    return queries.offers.timeline(
        sid,
        instance_id=iid,
        start_time=start,
        end_time=end,
        offset=page_offset,
        limit=page_limit,
    )


__all__ = ["TOOL_DEFINITION", "get_offer_timeline"]
