"""比较用户明确授权的多个解析会话的 Tool。"""
from __future__ import annotations

from typing import Any, Iterable

from someip.analysis.queries import SessionComparisonQuery, ensure_session_queries

from .support import require_session

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "compare_sessions",
        "description": (
            "将当前解析记录作为基线，与用户在 AI 面板中明确授权的其他记录比较服务、"
            "Offer、订阅、Notification 数量和异常差异。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_ids": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 128},
                    "minItems": 1,
                    "maxItems": 3,
                    "description": "一个到三个已授权的目标解析会话 ID，不要包含当前会话。",
                },
            },
            "required": ["session_ids"],
            "additionalProperties": False,
        },
    },
}


def compare_sessions(
    current_session_id: str,
    session_ids: Any,
    allowed_session_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """校验显式白名单后加载会话，并把纯比较逻辑交给查询层。"""
    if not isinstance(session_ids, list):
        raise ValueError("session_ids 必须是数组")
    requested = []
    for value in session_ids:
        if not isinstance(value, str):
            raise ValueError("session_ids 中的每一项都必须是字符串")
        session_id = str(value or "").strip()
        if not session_id or session_id == current_session_id or session_id in requested:
            continue
        requested.append(session_id)
    if not 1 <= len(requested) <= 3:
        raise ValueError("必须提供一到三个不重复的目标会话 ID")

    allowed = {str(value) for value in allowed_session_ids}
    denied = [session_id for session_id in requested if session_id not in allowed]
    if denied:
        raise ValueError(
            "目标会话未获得本轮访问授权，请先在 AI 面板勾选解析记录: "
            + ", ".join(denied)
        )

    states = [require_session(current_session_id)]
    states.extend(require_session(session_id) for session_id in requested)
    snapshots = [
        {
            "session_id": state.session_id,
            "pcap_name": getattr(state, "pcap_name", ""),
            "total_messages": getattr(state, "total_messages", len(state.messages)),
            "parsed_count": getattr(state, "parsed_count", 0),
            "queries": ensure_session_queries(state),
        }
        for state in states
    ]
    return SessionComparisonQuery.compare(snapshots)


__all__ = ["TOOL_DEFINITION", "compare_sessions"]
