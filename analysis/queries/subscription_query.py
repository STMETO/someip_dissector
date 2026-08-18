"""订阅诊断报告与订阅生命周期的统一查询。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from analysis.sd_diagnostic import build_subscription_report

from .evidence import (
    build_message_evidence,
    event_sort_key,
    format_hex,
    header_int,
    in_time_range,
)
from .message_query import MessageQuery
from .sd_query import SdRecordQuery


class SubscriptionQuery:
    """共享 SD/Notification 索引，保证页面报告和 AI 结果使用同一份事实。"""

    def __init__(
        self,
        records: SdRecordQuery,
        messages: MessageQuery,
        registry: Any = None,
    ):
        self._records = records
        self._messages = messages
        self._registry = registry
        # 报告在会话索引构建时生成一次，后续页面刷新和 Tool 调用不再扫描全部报文。
        self._report = build_subscription_report(
            [],
            registry,
            records=records.all_records,
            notifications=messages.notification_evidence,
        )

    def report(self) -> dict[str, Any]:
        """返回会话级订阅报告；调用方必须按只读方式使用。"""
        return self._report

    def timeline(
        self,
        service_id: int,
        *,
        eventgroup_id: int | None = None,
        instance_id: int | None = None,
        client_ip: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        offset: int = 0,
        limit: int = 80,
    ) -> dict[str, Any]:
        """还原 Subscribe、Ack、Nack、StopSubscribe 和关联 Notification。"""
        lifecycle: list[dict[str, Any]] = []
        clients_by_eventgroup: dict[int, set[str]] = defaultdict(set)
        action_groups = (
            ("SubscribeEventGroup", "subscribes"),
            ("StopSubscribeEventGroup", "stop_subscribes"),
            ("SubscribeEventGroupAck", "subscribe_acks"),
            ("SubscribeEventGroupNack", "subscribe_nacks"),
        )

        for action, category in action_groups:
            for record in self._records.records(category, service_id):
                eg_id = int(record.get("eventgroup_id", 0))
                evidence = record["evidence"]
                if eventgroup_id is not None and eg_id != eventgroup_id:
                    continue
                if instance_id is not None and record["instance_id"] != instance_id:
                    continue

                # Subscribe 源地址是客户端，Ack/Nack 目标地址才是客户端。
                record_client = (
                    record["ecu"]
                    if action in {"SubscribeEventGroup", "StopSubscribeEventGroup"}
                    else evidence.get("dst_ip")
                )
                if action == "SubscribeEventGroup" and record_client:
                    clients_by_eventgroup[eg_id].add(str(record_client))
                if client_ip and record_client != client_ip:
                    continue
                if not in_time_range(evidence, start_time, end_time):
                    continue
                lifecycle.append({
                    "action": action,
                    "service_id": format_hex(service_id),
                    "instance_id": format_hex(int(record["instance_id"])),
                    "eventgroup_id": format_hex(eg_id),
                    "eventgroup_name": _eventgroup_name(
                        self._registry, service_id, eg_id
                    ),
                    "client_ip": record_client,
                    "server_ip": (
                        evidence.get("dst_ip")
                        if action in {"SubscribeEventGroup", "StopSubscribeEventGroup"}
                        else record["ecu"]
                    ),
                    "ttl_seconds": int(record.get("ttl", 0)),
                    "evidence": evidence,
                })

        observed_eventgroups = set(clients_by_eventgroup)
        if eventgroup_id is not None:
            observed_eventgroups.add(eventgroup_id)

        # Notification 在线上不携带 EventGroup ID，只在这里应用项目约定的关联规则。
        for message in self._messages.notifications_for_service(service_id):
            method_id = header_int(message, "method_id")
            evidence = build_message_evidence(message, kind="Notification")
            if not in_time_range(evidence, start_time, end_time):
                continue
            for eg_id in observed_eventgroups:
                if method_id not in {eg_id, eg_id | 0x8000}:
                    continue
                if client_ip and client_ip not in clients_by_eventgroup.get(eg_id, set()):
                    continue
                lifecycle.append({
                    "action": "Notification",
                    "service_id": format_hex(service_id),
                    "eventgroup_id": format_hex(eg_id),
                    "eventgroup_name": _eventgroup_name(
                        self._registry, service_id, eg_id
                    ),
                    "method_id": format_hex(method_id),
                    "method_name": _method_or_event_name(
                        self._registry, service_id, method_id
                    ),
                    "server_ip": evidence.get("src_ip"),
                    "destination_ip": evidence.get("dst_ip"),
                    "evidence": evidence,
                })

        lifecycle.sort(key=event_sort_key)
        page = lifecycle[offset:offset + limit]
        action_counts: dict[str, int] = defaultdict(int)
        for event in lifecycle:
            action_counts[event["action"]] += 1
        return {
            "service_id": format_hex(service_id),
            "eventgroup_filter": (
                format_hex(eventgroup_id) if eventgroup_id is not None else None
            ),
            "instance_filter": format_hex(instance_id) if instance_id is not None else None,
            "client_filter": client_ip,
            "summary": {
                "event_count": len(lifecycle),
                "action_counts": dict(action_counts),
                "eventgroups": [format_hex(value) for value in sorted(observed_eventgroups)],
                "subscribing_clients": sorted({
                    client
                    for clients in clients_by_eventgroup.values()
                    for client in clients
                }),
            },
            "association_rule": (
                "Notification 不直接携带 EventGroup ID；当前按 method_id 等于 "
                "eventgroup_id 或 eventgroup_id|0x8000 进行关联"
            ),
            "offset": offset,
            "next_offset": offset + len(page) if offset + len(page) < len(lifecycle) else None,
            "events": page,
        }


def _eventgroup_name(registry: Any, service_id: int, eventgroup_id: int) -> str | None:
    try:
        return registry.lookup_eventgroup_name(service_id, eventgroup_id) if registry else None
    except Exception:
        return None


def _method_or_event_name(registry: Any, service_id: int, method_id: int) -> str | None:
    """按事件优先、方法其次的顺序解析 ARXML 名称。"""
    if not registry:
        return None
    try:
        for candidate in (method_id & 0x7FFF, method_id):
            name = registry.lookup_event_name(service_id, candidate)
            if name:
                return name
        for candidate in (method_id & 0x7FFF, method_id):
            name = registry.lookup_method_name(service_id, candidate)
            if name:
                return name
    except Exception:
        return None
    return None


__all__ = ["SubscriptionQuery"]
