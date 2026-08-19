"""按服务和成员读取 ARXML 定义的 Tool。"""
from __future__ import annotations

from typing import Any

from .support import parse_int, parse_text, require_queries

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_arxml_definition",
        "description": (
            "查询 ARXML 中的 Service、Method、Event、EventGroup、参数和字段类型定义；"
            "一次只读取一个服务，不返回整份 ARXML。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service_id": {"type": "string", "description": "必填 Service ID。"},
                "member_kind": {
                    "type": "string",
                    "description": "可选 all、method、event 或 eventgroup，默认 all。",
                },
                "member_id": {"type": "string", "description": "可选 Method/Event/EventGroup ID。"},
                "field_path": {
                    "type": "string", "maxLength": 512,
                    "description": "可选字段路径，例如 status.speed；提供后只返回匹配字段定义。",
                },
            },
            "required": ["service_id"],
            "additionalProperties": False,
        },
    },
}


def get_arxml_definition(
    session_id: str,
    service_id: Any,
    member_kind: Any = None,
    member_id: Any = None,
    field_path: Any = None,
) -> dict[str, Any]:
    """校验 ARXML 查询范围并调用公开定义查询接口。"""
    _, queries = require_queries(session_id)
    return queries.arxml.query(
        int(parse_int(service_id, "Service ID", required=True)),
        member_kind=parse_text(member_kind, "member_kind", max_length=32) or "all",
        member_id=parse_int(member_id, "成员 ID"),
        field_path=parse_text(field_path, "field_path", max_length=512),
    )


__all__ = ["TOOL_DEFINITION", "get_arxml_definition"]
