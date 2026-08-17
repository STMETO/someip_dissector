"""按 ID 或 ARXML 名称查找服务的 Tool。"""
from __future__ import annotations

from collections import Counter
from typing import Any

from analysis.sd_diagnostic import build_subscription_report, build_message_evidence
from assistant.tool_support import (
    clamp_limit,
    format_hex,
    lookup_service_name,
    message_service_ids,
    require_session,
)

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
    """合并抓包和 ARXML 注册表中的服务，并提供首次出现证据。"""
    state = require_session(session_id)
    max_results = clamp_limit(limit, default=20, maximum=50)
    query_text = str(query or "").strip()
    query_id = _try_parse_id(query_text)

    names: dict[int, str | None] = {}
    if state.registry and hasattr(state.registry, "list_services"):
        names.update(dict(state.registry.list_services()))

    message_counts: Counter[int] = Counter()
    first_evidence: dict[int, dict[str, Any]] = {}
    for message in state.messages:
        for service_id in message_service_ids(message):
            if service_id == 0xFFFF:
                continue
            message_counts[service_id] += 1
            first_evidence.setdefault(service_id, build_message_evidence(message))
            names.setdefault(service_id, lookup_service_name(state.registry, service_id))

    report = build_subscription_report(state.messages, state.registry)
    diagnostics = {row["service_id"]: row for row in report.get("services", [])}

    rows = []
    for service_id, name in sorted(names.items()):
        if not _matches(service_id, name, query_text, query_id):
            continue
        diagnostic = diagnostics.get(service_id, {})
        rows.append({
            "service_id": format_hex(service_id),
            "service_id_dec": service_id,
            "service_name": name or None,
            "message_count": message_counts.get(service_id, 0),
            "offer_observed": bool(diagnostic.get("has_offer")),
            "server_ecus": diagnostic.get("server_ecus", []),
            "instance_ids": [format_hex(value) for value in diagnostic.get("instance_ids", [])],
            "first_evidence": first_evidence.get(service_id),
        })

    return {
        "query": query_text or None,
        "matched_service_count": len(rows),
        "services": rows[:max_results],
        "truncated": len(rows) > max_results,
    }


def _try_parse_id(query: str) -> int | None:
    if not query:
        return None
    try:
        value = int(query, 0)
    except ValueError:
        try:
            value = int(query, 10) if query.isdigit() else -1
        except ValueError:
            return None
    return value if 0 <= value <= 0xFFFF else None


def _matches(
    service_id: int,
    name: str | None,
    query: str,
    query_id: int | None,
) -> bool:
    if not query:
        return True
    if query_id is not None:
        return service_id == query_id
    normalized = query.casefold()
    return normalized in (name or "").casefold() or normalized in format_hex(service_id).casefold()


__all__ = ["TOOL_DEFINITION", "find_service"]
