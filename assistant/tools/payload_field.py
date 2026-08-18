"""按路径查询单条报文深层 Payload 字段的 Tool。"""
from __future__ import annotations

from typing import Any

from assistant.tool_support import parse_int, require_queries

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_payload_field",
        "description": (
            "按消息索引和字段路径读取一个反序列化 Payload 节点。"
            "分析深层 Payload 时优先使用本工具，避免返回完整解析树。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message_index": {
                    "type": "integer",
                    "description": "必填消息索引，即消息列表中的 Index。",
                },
                "field_path": {
                    "type": "string",
                    "description": "必填点分隔字段路径，例如 vehicle.status.speed。",
                },
            },
            "required": ["message_index", "field_path"],
            "additionalProperties": False,
        },
    },
}


def get_payload_field(
    session_id: str,
    message_index: Any,
    field_path: Any,
) -> dict[str, Any]:
    """只返回目标字段和直接子字段名称，严格限制模型上下文。"""
    _, queries = require_queries(session_id)
    index = int(parse_int(
        message_index,
        "message_index",
        required=True,
        minimum=0,
        maximum=100_000_000,
    ))
    path = str(field_path or "").strip()
    if not path:
        raise ValueError("field_path 不能为空")
    if len(path) > 1_000:
        raise ValueError("field_path 长度不能超过 1000 个字符")
    return queries.signals.payload_field(index, path)


__all__ = ["TOOL_DEFINITION", "get_payload_field"]
