"""查询 Notification 频率、间隔及信号字段统计的 Tool。"""
from __future__ import annotations

from typing import Any

from .support import parse_float, parse_int, require_queries

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_notification_statistics",
        "description": (
            "统计 Notification 数量、首尾时间、报文间隔、源/目标 IP；"
            "提供 field_path 时同时统计该 Payload 数值字段的范围、均值和跳变次数。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service_id": {"type": "string", "description": "可选 Service ID。"},
                "method_id": {"type": "string", "description": "可选 Method/Event ID。"},
                "field_path": {"type": "string", "description": "可选 Payload 字段路径，例如 status.speed。"},
                "start_time": {"type": "number", "description": "可选起始 epoch 秒。"},
                "end_time": {"type": "number", "description": "可选结束 epoch 秒。"},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


def get_notification_statistics(
    session_id: str,
    service_id: Any = None,
    method_id: Any = None,
    field_path: Any = None,
    start_time: Any = None,
    end_time: Any = None,
) -> dict[str, Any]:
    """校验筛选条件并调用统一信号查询层。"""
    _, queries = require_queries(session_id)
    sid = parse_int(service_id, "Service ID")
    mid = parse_int(method_id, "Method/Event ID")
    if mid is not None and sid is None:
        raise ValueError("按 Method/Event ID 查询时必须同时提供 Service ID")
    path = str(field_path or "").strip() or None
    if path is not None and mid is None:
        raise ValueError("统计 Payload 字段时必须提供 Service ID 和 Method/Event ID")
    start = parse_float(start_time, "start_time")
    end = parse_float(end_time, "end_time")
    if start is not None and end is not None and start > end:
        raise ValueError("start_time 不能大于 end_time")
    return queries.signals.notification_statistics(
        service_id=sid,
        method_id=mid,
        field_path=path,
        start_time=start,
        end_time=end,
    )


__all__ = ["TOOL_DEFINITION", "get_notification_statistics"]
