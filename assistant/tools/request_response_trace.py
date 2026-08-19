"""查询 SOME/IP Request/Response 关联和响应时间的 Tool。"""
from __future__ import annotations

from typing import Any

from .support import clamp_limit, parse_float, parse_int, parse_text, require_queries

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_request_response_trace",
        "description": (
            "按 Client ID、Session ID、Service 和 Method 关联 SOME/IP Request/Response，"
            "查询响应时间、缺失响应、孤立响应和 Error 返回。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service_id": {"type": "string", "description": "可选 Service ID。"},
                "method_id": {"type": "string", "description": "可选 Method ID。"},
                "client_id": {"type": "string", "description": "可选 SOME/IP Client ID。"},
                "session_id": {"type": "string", "description": "可选 SOME/IP Session ID。"},
                "status": {
                    "type": "string",
                    "description": (
                        "可选状态：matched、error_response、missing_response、"
                        "unmatched_response、no_return。"
                    ),
                },
                "start_time": {"type": "number", "description": "可选起始 epoch 秒。"},
                "end_time": {"type": "number", "description": "可选结束 epoch 秒。"},
                "offset": {"type": "integer", "description": "分页偏移，默认 0。"},
                "limit": {"type": "integer", "description": "返回数量，默认 80，最大 200。"},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


def get_request_response_trace(
    session_id: str,
    service_id: Any = None,
    method_id: Any = None,
    client_id: Any = None,
    someip_session_id: Any = None,
    status: Any = None,
    start_time: Any = None,
    end_time: Any = None,
    offset: Any = None,
    limit: Any = None,
) -> dict[str, Any]:
    """校验关联条件并调用会话级 RPC 查询。"""
    _, queries = require_queries(session_id)
    start = parse_float(start_time, "start_time")
    end = parse_float(end_time, "end_time")
    if start is not None and end is not None and start > end:
        raise ValueError("start_time 不能大于 end_time")
    return queries.request_responses.search(
        service_id=parse_int(service_id, "Service ID"),
        method_id=parse_int(method_id, "Method ID"),
        client_id=parse_int(client_id, "Client ID"),
        session_id=parse_int(someip_session_id, "Session ID"),
        status=parse_text(status, "status", max_length=64) or "",
        start_time=start,
        end_time=end,
        offset=int(parse_int(offset, "offset", minimum=0, maximum=10_000_000) or 0),
        limit=clamp_limit(limit, default=80, maximum=200),
    )


__all__ = ["TOOL_DEFINITION", "get_request_response_trace"]
