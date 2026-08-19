"""多解析会话的结构化差异比较。"""
from __future__ import annotations

from typing import Any

from .evidence import format_hex


class SessionComparisonQuery:
    """比较调用方明确授权的会话快照，不负责读取 Web 会话存储。"""

    @staticmethod
    def compare(sessions: list[dict[str, Any]]) -> dict[str, Any]:
        if len(sessions) < 2:
            raise ValueError("至少需要两个解析会话才能比较")
        snapshots = [_snapshot(item) for item in sessions]
        baseline = snapshots[0]
        comparisons = []
        for target in snapshots[1:]:
            comparisons.append({
                "session_id": target["session_id"],
                "pcap_name": target["pcap_name"],
                "relative_to_session_id": baseline["session_id"],
                "services_added": _format_ids(target["services"] - baseline["services"]),
                "services_removed": _format_ids(baseline["services"] - target["services"]),
                "offers_added": _format_pairs(
                    target["offers"] - baseline["offers"], "instance_id"
                ),
                "offers_removed": _format_pairs(
                    baseline["offers"] - target["offers"], "instance_id"
                ),
                "subscriptions_added": _format_pairs(
                    target["subscriptions"] - baseline["subscriptions"],
                    "eventgroup_id",
                ),
                "subscriptions_removed": _format_pairs(
                    baseline["subscriptions"] - target["subscriptions"],
                    "eventgroup_id",
                ),
                "notification_deltas": _notification_deltas(
                    baseline["notifications"], target["notifications"]
                ),
                "anomalies_added": _format_anomalies(
                    target["anomalies"] - baseline["anomalies"]
                ),
                "anomalies_resolved": _format_anomalies(
                    baseline["anomalies"] - target["anomalies"]
                ),
            })
        return {
            "baseline_session_id": baseline["session_id"],
            "sessions": [_public_snapshot(snapshot) for snapshot in snapshots],
            "comparisons": comparisons,
            "fact_scope": "只比较用户本轮明确授权的解析记录及其抓包内观察结果",
        }


def _snapshot(item: dict[str, Any]) -> dict[str, Any]:
    queries = item["queries"]
    report = queries.subscriptions.report()
    services: set[int] = {
        service_id for service_id in queries.messages.service_ids if service_id != 0xFFFF
    }
    offers: set[tuple[int, int]] = set()
    subscriptions: set[tuple[int, int]] = set()
    notifications: dict[tuple[int, int], int] = {
        key: len(evidence)
        for key, evidence in queries.messages.notification_evidence.items()
    }
    anomalies: set[tuple[str, int, int | None]] = set()

    for service in report.get("services", []):
        service_id = int(service.get("service_id", 0))
        services.add(service_id)
        for instance in service.get("offer_instances", []):
            if int(instance.get("offer_count", 0)) > 0:
                offers.add((service_id, int(instance.get("instance_id", 0))))
            if instance.get("offer_conflict"):
                anomalies.add(("offer_conflict", service_id, int(instance.get("instance_id", 0))))
        eventgroups = service.get("eventgroups", [])
        if service.get("has_offer") and not eventgroups:
            anomalies.add(("offered_without_subscription", service_id, None))
        if not service.get("has_offer") and any(eg.get("subscribed") for eg in eventgroups):
            anomalies.add(("subscribed_without_offer", service_id, None))
        for eventgroup in eventgroups:
            eventgroup_id = int(eventgroup.get("eventgroup_id", 0))
            if eventgroup.get("subscribed"):
                subscriptions.add((service_id, eventgroup_id))
            if eventgroup.get("nacked"):
                anomalies.add(("nacked", service_id, eventgroup_id))
            elif service.get("has_offer") and eventgroup.get("subscribed") and not eventgroup.get("acked"):
                anomalies.add(("subscribed_without_ack", service_id, eventgroup_id))
            elif (
                service.get("has_offer")
                and eventgroup.get("subscribed")
                and eventgroup.get("acked")
                and int(eventgroup.get("notification_count", 0)) == 0
            ):
                anomalies.add(("subscribed_without_notification", service_id, eventgroup_id))

    return {
        "session_id": item["session_id"],
        "pcap_name": item.get("pcap_name", ""),
        "total_messages": int(item.get("total_messages", len(queries.messages.all))),
        "parsed_count": int(item.get("parsed_count", 0)),
        "services": services,
        "offers": offers,
        "subscriptions": subscriptions,
        "notifications": notifications,
        "anomalies": anomalies,
    }


def _public_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": snapshot["session_id"],
        "pcap_name": snapshot["pcap_name"],
        "total_messages": snapshot["total_messages"],
        "parsed_count": snapshot["parsed_count"],
        "service_count": len(snapshot["services"]),
        "offered_instance_count": len(snapshot["offers"]),
        "subscribed_eventgroup_count": len(snapshot["subscriptions"]),
        "notification_count": sum(snapshot["notifications"].values()),
        "anomaly_count": len(snapshot["anomalies"]),
    }


def _format_ids(values: set[int]) -> list[str]:
    return [format_hex(value) for value in sorted(values)]


def _format_pairs(
    values: set[tuple[int, int]],
    member_key: str,
) -> list[dict[str, str]]:
    return [
        {"service_id": format_hex(service_id), member_key: format_hex(member_id)}
        for service_id, member_id in sorted(values)
    ]


def _format_anomalies(
    values: set[tuple[str, int, int | None]],
) -> list[dict[str, Any]]:
    return [
        {
            "anomaly_type": anomaly_type,
            "service_id": format_hex(service_id),
            "member_id": format_hex(member_id) if member_id is not None else None,
        }
        for anomaly_type, service_id, member_id in sorted(
            values, key=lambda value: (value[0], value[1], value[2] or -1)
        )
    ]


def _notification_deltas(
    baseline: dict[tuple[int, int], int],
    target: dict[tuple[int, int], int],
) -> list[dict[str, Any]]:
    result = []
    for service_id, method_id in sorted(set(baseline) | set(target)):
        before = baseline.get((service_id, method_id), 0)
        after = target.get((service_id, method_id), 0)
        if before == after:
            continue
        result.append({
            "service_id": format_hex(service_id),
            "method_or_event_id": format_hex(method_id),
            "baseline_count": before,
            "target_count": after,
            "delta": after - before,
        })
    return result


__all__ = ["SessionComparisonQuery"]
