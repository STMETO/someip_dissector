"""按字段路径和值检索反序列化 Payload 的 Tool。"""
from __future__ import annotations

from typing import Any

from .support import clamp_limit, parse_float, parse_int, parse_text, require_queries

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_payload_values",
        "description": (
            "按字段路径检索反序列化 Payload，可按精确值、文本包含、数值范围、"
            "Service、Method 和时间过滤。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "field_path": {
                    "type": "string", "minLength": 1, "maxLength": 512,
                    "description": "必填字段路径，例如 status.speed。",
                },
                "service_id": {"type": "string", "description": "可选 Service ID。"},
                "method_id": {"type": "string", "description": "可选 Method/Event ID。"},
                "exact_value": {
                    "type": "string", "maxLength": 1024,
                    "description": "可选精确值；数值和布尔也使用字符串，例如 42 或 true。",
                },
                "text_contains": {
                    "type": "string", "maxLength": 512,
                    "description": "可选文本包含条件。",
                },
                "minimum": {"type": "number", "description": "可选数值下限，包含边界。"},
                "maximum": {"type": "number", "description": "可选数值上限，包含边界。"},
                "start_time": {"type": "number", "description": "可选起始 epoch 秒。"},
                "end_time": {"type": "number", "description": "可选结束 epoch 秒。"},
                "offset": {"type": "integer", "description": "分页偏移，默认 0。"},
                "limit": {"type": "integer", "description": "返回数量，默认 80，最大 200。"},
            },
            "required": ["field_path"],
            "additionalProperties": False,
        },
    },
}


def search_payload_values(
    session_id: str,
    field_path: Any,
    service_id: Any = None,
    method_id: Any = None,
    exact_value: Any = None,
    text_contains: Any = None,
    minimum: Any = None,
    maximum: Any = None,
    start_time: Any = None,
    end_time: Any = None,
    offset: Any = None,
    limit: Any = None,
) -> dict[str, Any]:
    """在统一查询层的字段路径懒索引上执行值过滤。"""
    _, queries = require_queries(session_id)
    start = parse_float(start_time, "start_time")
    end = parse_float(end_time, "end_time")
    if start is not None and end is not None and start > end:
        raise ValueError("start_time 不能大于 end_time")
    if isinstance(exact_value, str) and len(exact_value) > 1024:
        raise ValueError("exact_value 长度不能超过 1024 个字符")
    return queries.payload_values.search(
        parse_text(field_path, "field_path", required=True, max_length=512) or "",
        service_id=parse_int(service_id, "Service ID"),
        method_id=parse_int(method_id, "Method/Event ID"),
        exact_value=exact_value,
        text_contains=parse_text(text_contains, "text_contains", max_length=512),
        minimum=parse_float(minimum, "minimum"),
        maximum=parse_float(maximum, "maximum"),
        start_time=start,
        end_time=end,
        offset=int(parse_int(offset, "offset", minimum=0, maximum=10_000_000) or 0),
        limit=clamp_limit(limit, default=80, maximum=200),
    )


__all__ = ["TOOL_DEFINITION", "search_payload_values"]
