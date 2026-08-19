"""按协议字段和网络端点检索 SOME/IP 报文的 Tool。"""
from __future__ import annotations

from typing import Any

from .support import (
    clamp_limit,
    compact_message,
    parse_float,
    parse_int,
    require_queries,
)

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_messages",
        "description": (
            "按 Service ID、Method/Event ID、消息类型、IP、SD Entry 类型、解析状态或时间范围检索报文。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service_id": {"type": "string", "description": "可选 Service ID。SD 报文会检查内部 Entry。"},
                "method_id": {"type": "string", "description": "可选 Method/Event ID。"},
                "message_type": {"type": "string", "description": "可选消息类型，例如 0x02、Notification、Offer。"},
                "src_ip": {"type": "string", "description": "可选源 IP，精确匹配。"},
                "dst_ip": {"type": "string", "description": "可选目标 IP，精确匹配。"},
                "sd_entry_type": {"type": "string", "description": "可选 SD Entry 类型，例如 OfferService。"},
                "parse_status": {"type": "string", "description": "可选解析状态，例如 ok 或 unresolved。"},
                "start_time": {"type": "number", "description": "可选起始 epoch 秒。"},
                "end_time": {"type": "number", "description": "可选结束 epoch 秒。"},
                "offset": {"type": "integer", "description": "分页偏移，默认 0。"},
                "limit": {"type": "integer", "description": "返回数量，默认 50，最大 200。"},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


def search_messages(
    session_id: str,
    service_id: Any = None,
    method_id: Any = None,
    message_type: Any = None,
    src_ip: Any = None,
    dst_ip: Any = None,
    sd_entry_type: Any = None,
    parse_status: Any = None,
    start_time: Any = None,
    end_time: Any = None,
    offset: Any = None,
    limit: Any = None,
) -> dict[str, Any]:
    """返回符合条件的紧凑报文摘要，原始详情由 message_detail 按索引读取。"""
    state, queries = require_queries(session_id)
    sid = parse_int(service_id, "Service ID")
    mid = parse_int(method_id, "Method/Event ID")
    type_filter = str(message_type or "").strip().casefold()
    src_filter = str(src_ip or "").strip() or None
    dst_filter = str(dst_ip or "").strip() or None
    entry_filter = str(sd_entry_type or "").strip().casefold()
    status_filter = str(parse_status or "").strip().casefold()
    start = parse_float(start_time, "start_time")
    end = parse_float(end_time, "end_time")
    page_offset = int(parse_int(offset, "offset", minimum=0, maximum=10_000_000) or 0)
    page_limit = clamp_limit(limit, default=50, maximum=200)

    found = queries.messages.search(
        service_id=sid,
        method_id=mid,
        message_type=type_filter,
        src_ip=src_filter,
        dst_ip=dst_filter,
        sd_entry_type=entry_filter,
        parse_status=status_filter,
        start_time=start,
        end_time=end,
        offset=page_offset,
        limit=page_limit,
    )
    page = [compact_message(message, state.registry) for message in found.messages]

    return {
        "filters": {
            "service_id": service_id,
            "method_id": method_id,
            "message_type": message_type,
            "src_ip": src_filter,
            "dst_ip": dst_filter,
            "sd_entry_type": sd_entry_type,
            "parse_status": parse_status,
            "start_time": start,
            "end_time": end,
        },
        "matched_message_count": found.total,
        "offset": page_offset,
        "next_offset": found.next_offset,
        "messages": page,
    }

__all__ = ["TOOL_DEFINITION", "search_messages"]
