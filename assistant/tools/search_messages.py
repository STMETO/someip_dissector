"""按协议字段和网络端点检索 SOME/IP 报文的 Tool。"""
from __future__ import annotations

from typing import Any

from assistant.tool_support import (
    clamp_limit,
    compact_message,
    header_int,
    in_time_range,
    message_service_ids,
    parse_float,
    parse_int,
    require_session,
)
from pcap_parsers.common import message_type_label

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
    state = require_session(session_id)
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

    matched_count = 0
    page: list[dict[str, Any]] = []
    for message in state.messages:
        if sid is not None and sid not in message_service_ids(message):
            continue
        if mid is not None and header_int(message, "method_id") != mid:
            continue
        if src_filter and message.get("src_ip") != src_filter:
            continue
        if dst_filter and message.get("dst_ip") != dst_filter:
            continue
        if status_filter and str(message.get("parse_status", "unresolved")).casefold() != status_filter:
            continue
        if type_filter and not _matches_message_type(message, type_filter):
            continue
        if entry_filter and not _matches_sd_entry(message, entry_filter):
            continue
        if not in_time_range(message, start, end):
            continue
        if page_offset <= matched_count < page_offset + page_limit:
            page.append(compact_message(message, state.registry))
        matched_count += 1

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
        "matched_message_count": matched_count,
        "offset": page_offset,
        "next_offset": page_offset + len(page) if page_offset + len(page) < matched_count else None,
        "messages": page,
    }


def _matches_message_type(message: dict[str, Any], query: str) -> bool:
    """同时匹配线上的数值类型和 SD 精确业务类型。"""
    value = header_int(message, "message_type")
    candidates = {
        str(value).casefold(),
        f"0x{value:02x}",
        message_type_label(value).casefold(),
        str(message.get("message_kind", "")).casefold(),
    }
    return any(query == candidate or query in candidate for candidate in candidates)


def _matches_sd_entry(message: dict[str, Any], query: str) -> bool:
    """检查一条 SD 报文中是否至少包含一个目标 Entry 类型。"""
    return any(
        query in str(entry.get("type", "")).casefold()
        for entry in message.get("sd", {}).get("entries", [])
    )


__all__ = ["TOOL_DEFINITION", "search_messages"]
