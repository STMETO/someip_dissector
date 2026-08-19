"""订阅诊断异常的结构化展开查询。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .evidence import format_hex
from .message_query import MessageQuery
from .subscription_query import SubscriptionQuery

ANOMALY_TYPES = (
    "offer_conflict",
    "offered_without_subscription",
    "subscribed_without_offer",
    "subscribed_without_ack",
    "nacked",
    "subscribed_without_notification",
)


class AnomalyDetailsQuery:
    """把订阅报告中的布尔状态转换为稳定、可筛选的异常记录。"""

    def __init__(self, subscriptions: SubscriptionQuery, messages: MessageQuery):
        self._items = self._build(subscriptions.report())
        timestamps = [
            float(message.get("timestamp_epoch") or 0.0) for message in messages.all
        ]
        self._capture_time_range = {
            "start_time": min(timestamps) if timestamps else None,
            "end_time": max(timestamps) if timestamps else None,
        }

    def query(
        self,
        *,
        anomaly_type: str = "all",
        service_id: int | None = None,
        offset: int = 0,
        limit: int = 80,
    ) -> dict[str, Any]:
        normalized = anomaly_type.strip().casefold() or "all"
        if normalized != "all" and normalized not in ANOMALY_TYPES:
            raise ValueError(f"anomaly_type 必须是 all 或 {', '.join(ANOMALY_TYPES)}")
        matched = [
            item for item in self._items
            if (normalized == "all" or item["anomaly_type"] == normalized)
            and (service_id is None or item["service_id_dec"] == service_id)
        ]
        counts: dict[str, int] = defaultdict(int)
        for item in matched:
            counts[item["anomaly_type"]] += 1
        page = [
            {key: value for key, value in item.items() if not key.endswith("_dec")}
            for item in matched[offset:offset + limit]
        ]
        return {
            "filters": {
                "anomaly_type": normalized,
                "service_id": format_hex(service_id) if service_id is not None else None,
            },
            "summary": {
                "anomaly_count": len(matched),
                "counts_by_type": dict(sorted(counts.items())),
            },
            "offset": offset,
            "next_offset": offset + len(page) if offset + len(page) < len(matched) else None,
            "anomalies": page,
            "capture_time_range": self._capture_time_range,
            "fact_scope": "异常仅依据当前抓包观察结果和项目订阅诊断规则生成",
        }

    @staticmethod
    def _build(report: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        items: list[dict[str, Any]] = []
        for service in report.get("services", []):
            service_id = int(service.get("service_id", 0))
            base = {
                "service_id": format_hex(service_id),
                "service_id_dec": service_id,
                "service_name": service.get("service_name") or None,
                "server_ecus": service.get("server_ecus", []),
            }
            if service.get("offer_conflict"):
                for instance in service.get("offer_instances", []):
                    if not instance.get("offer_conflict"):
                        continue
                    items.append({
                        **base,
                        "anomaly_type": "offer_conflict",
                        "instance_id": format_hex(int(instance.get("instance_id", 0))),
                        "client_ecus": [],
                        "evidence": instance.get("offer_evidence", []),
                        "diagnosis": "同一 Service ID 和 Instance ID 被多个 ECU 发布 Offer",
                    })

            eventgroups = service.get("eventgroups", [])
            if service.get("has_offer") and not eventgroups:
                items.append({
                    **base,
                    "anomaly_type": "offered_without_subscription",
                    "client_ecus": [],
                    "evidence": service.get("offer_evidence", []),
                    "diagnosis": "观察到 Offer，但未观察到客户端 Subscribe",
                })
            if not service.get("has_offer") and any(eg.get("subscribed") for eg in eventgroups):
                items.append({
                    **base,
                    "anomaly_type": "subscribed_without_offer",
                    "client_ecus": sorted({
                        client for eg in eventgroups for client in eg.get("client_ecus", [])
                    }),
                    "evidence": [
                        evidence
                        for eg in eventgroups
                        for evidence in eg.get("subscribe_evidence", [])
                    ][:12],
                    "diagnosis": "观察到 Subscribe，但未观察到服务 Offer",
                })

            for eventgroup in eventgroups:
                eventgroup_id = int(eventgroup.get("eventgroup_id", 0))
                common = {
                    **base,
                    "eventgroup_id": format_hex(eventgroup_id),
                    "eventgroup_id_dec": eventgroup_id,
                    "eventgroup_name": eventgroup.get("eventgroup_name") or None,
                    "client_ecus": eventgroup.get("client_ecus", []),
                }
                if service.get("has_offer") and not eventgroup.get("subscribed"):
                    items.append({
                        **common,
                        "anomaly_type": "offered_without_subscription",
                        "evidence": service.get("offer_evidence", []),
                        "diagnosis": "EventGroup 所属服务已 Offer，但未观察到 Subscribe",
                    })
                if eventgroup.get("nacked"):
                    items.append({
                        **common,
                        "anomaly_type": "nacked",
                        "evidence": eventgroup.get("nack_evidence", []),
                        "diagnosis": "观察到 Subscribe Nack",
                    })
                elif service.get("has_offer") and eventgroup.get("subscribed") and not eventgroup.get("acked"):
                    items.append({
                        **common,
                        "anomaly_type": "subscribed_without_ack",
                        "evidence": eventgroup.get("subscribe_evidence", []),
                        "diagnosis": "观察到 Subscribe，但未观察到 Ack",
                    })
                elif (
                    service.get("has_offer")
                    and eventgroup.get("subscribed")
                    and eventgroup.get("acked")
                    and int(eventgroup.get("notification_count", 0)) == 0
                ):
                    items.append({
                        **common,
                        "anomaly_type": "subscribed_without_notification",
                        "evidence": (
                            eventgroup.get("subscribe_evidence", [])
                            + eventgroup.get("ack_evidence", [])
                        )[:12],
                        "diagnosis": "已观察到 Offer、Subscribe 和 Ack，但未观察到 Notification",
                    })

        for item in items:
            item["evidence_time_range"] = _evidence_time_range(item.get("evidence", []))
        return tuple(items)


def _evidence_time_range(evidence: list[dict[str, Any]]) -> dict[str, float] | None:
    timestamps = [
        float(item.get("timestamp_epoch") or 0.0)
        for item in evidence
        if item.get("timestamp_epoch") is not None
    ]
    if not timestamps:
        return None
    return {"start_time": min(timestamps), "end_time": max(timestamps)}


__all__ = ["ANOMALY_TYPES", "AnomalyDetailsQuery"]
