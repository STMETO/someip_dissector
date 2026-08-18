"""服务 Offer 生命周期和冲突状态的统一查询。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .evidence import format_hex, in_time_range
from .sd_query import SdRecordQuery


class OfferQuery:
    """复用 SD 记录索引查询 Offer，统一 Service+Instance 冲突规则。"""

    def __init__(self, records: SdRecordQuery, registry: Any = None):
        self._records = records
        self._registry = registry

    def timeline(
        self,
        service_id: int,
        *,
        instance_id: int | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """返回按抓包时间排序的 Offer/StopOffer 生命周期。"""
        timeline: list[dict[str, Any]] = []
        for action, category in (
            ("OfferService", "offers"),
            ("StopOfferService", "stop_offers"),
        ):
            for record in self._records.records(category, service_id):
                evidence = record["evidence"]
                if instance_id is not None and record["instance_id"] != instance_id:
                    continue
                if not in_time_range(evidence, start_time, end_time):
                    continue
                timeline.append({
                    "action": action,
                    "service_id": format_hex(service_id),
                    "instance_id": format_hex(int(record["instance_id"])),
                    "server_ecu": record["ecu"],
                    "ttl_seconds": int(record["ttl"]),
                    "major_version": int(record["major_version"]),
                    "minor_version": int(record["minor_version"]),
                    "evidence": evidence,
                })

        timeline.sort(key=lambda item: (
            float(item["evidence"].get("timestamp_epoch") or 0.0),
            int(item["evidence"].get("message_index") or 0),
            int(item["evidence"].get("entry_index") or 0),
        ))
        page = timeline[offset:offset + limit]
        offers = [item for item in timeline if item["action"] == "OfferService"]
        servers_by_instance: dict[str, set[str]] = defaultdict(set)
        for item in offers:
            servers_by_instance[item["instance_id"]].add(item["server_ecu"])

        # 不同 Instance 允许由不同 ECU 发布；同一个 Instance 多发布方才算冲突。
        instance_sources = [
            {
                "instance_id": instance_hex,
                "server_ecus": sorted(instance_servers),
                "offer_conflict": len(instance_servers) > 1,
            }
            for instance_hex, instance_servers in sorted(servers_by_instance.items())
        ]
        return {
            "service_id": format_hex(service_id),
            "service_name": _service_name(self._registry, service_id),
            "instance_filter": format_hex(instance_id) if instance_id is not None else None,
            "summary": {
                "offer_message_count": len(offers),
                "stop_offer_message_count": sum(
                    item["action"] == "StopOfferService" for item in timeline
                ),
                "server_ecus": sorted({item["server_ecu"] for item in offers}),
                "instances": instance_sources,
                "offer_conflict_observed": any(
                    item["offer_conflict"] for item in instance_sources
                ),
            },
            "total_event_count": len(timeline),
            "offset": offset,
            "next_offset": offset + len(page) if offset + len(page) < len(timeline) else None,
            "events": page,
        }


def _service_name(registry: Any, service_id: int) -> str | None:
    """注册表缺失或 ARXML 不完整时返回 None，不让查询失败。"""
    try:
        return registry.lookup_service_name(service_id) if registry else None
    except Exception:
        return None


__all__ = ["OfferQuery"]
