"""按 ID 或 ARXML 名称查找服务的 AI Tool。"""
from __future__ import annotations

from typing import Any

from assistant.tool_support import clamp_limit, require_queries

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "find_service",
        "description": "按十六进制 ID、十进制 ID 或 ARXML 服务名称查找当前会话中的服务。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "可选查询词，例如 0x0A01、2561 或 Parking。为空时列出服务。",
                },
                "limit": {
                    "type": "integer",
                    "description": "最大返回数量，默认 20，最大 50。",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


def find_service(session_id: str, query: Any = None, limit: Any = None) -> dict[str, Any]:
    """校验 Tool 参数后调用统一服务查询，不在 Tool 内重复遍历消息。"""
    _, queries = require_queries(session_id)
    max_results = clamp_limit(limit, default=20, maximum=50)
    return queries.services.find(str(query or "").strip(), limit=max_results)


__all__ = ["TOOL_DEFINITION", "find_service"]
