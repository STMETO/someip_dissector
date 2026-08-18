"""合并抓包索引、ARXML 名称和订阅诊断的服务查询。"""
from __future__ import annotations

from typing import Any

from .evidence import build_message_evidence, format_hex
from .message_query import MessageQuery
from .subscription_query import SubscriptionQuery


class ServiceQuery:
    """提供按 ID/名称查找服务的统一实现。"""

    def __init__(
        self,
        messages: MessageQuery,
        subscriptions: SubscriptionQuery,
        registry: Any = None,
    ):
        self._messages = messages
        self._subscriptions = subscriptions
        self._registry = registry

    def find(self, query: str = "", *, limit: int = 20) -> dict[str, Any]:
        """列出或检索服务，同时返回首次出现证据与 Offer 状态。"""
        query_text = query.strip()
        query_id = _try_parse_id(query_text)
        names: dict[int, str | None] = {}
        if self._registry and hasattr(self._registry, "list_services"):
            names.update(dict(self._registry.list_services()))
        for service_id in self._messages.service_ids:
            if service_id == 0xFFFF:
                continue
            names.setdefault(service_id, _service_name(self._registry, service_id))

        report = self._subscriptions.report()
        diagnostics = {row["service_id"]: row for row in report.get("services", [])}
        rows = []
        for service_id, name in sorted(names.items()):
            if not _matches(service_id, name, query_text, query_id):
                continue
            messages = self._messages.for_service(service_id)
            diagnostic = diagnostics.get(service_id, {})
            rows.append({
                "service_id": format_hex(service_id),
                "service_id_dec": service_id,
                "service_name": name or None,
                "message_count": len(messages),
                "offer_observed": bool(diagnostic.get("has_offer")),
                "server_ecus": diagnostic.get("server_ecus", []),
                "instance_ids": [
                    format_hex(value) for value in diagnostic.get("instance_ids", [])
                ],
                "first_evidence": (
                    build_message_evidence(messages[0]) if messages else None
                ),
            })
        return {
            "query": query_text or None,
            "matched_service_count": len(rows),
            "services": rows[:limit],
            "truncated": len(rows) > limit,
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


def _service_name(registry: Any, service_id: int) -> str | None:
    try:
        return registry.lookup_service_name(service_id) if registry else None
    except Exception:
        return None


__all__ = ["ServiceQuery"]
