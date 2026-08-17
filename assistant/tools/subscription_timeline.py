"""查询 SOME/IP-SD 订阅生命周期时间线的 Tool。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from analysis.sd_diagnostic import build_message_evidence, extract_sd_records
from assistant.tool_support import (
    clamp_limit,
    format_hex,
    header_int,
    in_time_range,
    lookup_method_or_event_name,
    parse_float,
    parse_int,
    require_session,
)
from pcap_parsers.common import SOMEIP_SD_SERVICE_ID, is_notification

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_subscription_timeline",
        "description": (
            "查询指定服务的 Subscribe、StopSubscribe、Ack、Nack 和关联的 "
            "Notification 时间线，可继续按 EventGroup、Instance 或客户端过滤。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service_id": {"type": "string", "description": "必填 Service ID，例如 0x0A01。"},
                "eventgroup_id": {"type": "string", "description": "可选 EventGroup ID。"},
                "instance_id": {"type": "string", "description": "可选 Instance ID。"},
                "client_ip": {"type": "string", "description": "可选订阅客户端 IP。"},
                "start_time": {"type": "number", "description": "可选起始 epoch 秒。"},
                "end_time": {"type": "number", "description": "可选结束 epoch 秒。"},
                "offset": {"type": "integer", "description": "分页偏移，默认 0。"},
                "limit": {"type": "integer", "description": "返回数量，默认 80，最大 200。"},
            },
            "required": ["service_id"],
            "additionalProperties": False,
        },
    },
}


def get_subscription_timeline(
    session_id: str,
    service_id: Any,
    eventgroup_id: Any = None,
    instance_id: Any = None,
    client_ip: Any = None,
    start_time: Any = None,
    end_time: Any = None,
    offset: Any = None,
    limit: Any = None,
) -> dict[str, Any]:
    """按抓包时间还原订阅生命周期，并保留每个状态的原始报文证据。"""
    state = require_session(session_id)
    sid = int(parse_int(service_id, "Service ID", required=True))
    eg_filter = parse_int(eventgroup_id, "EventGroup ID")
    instance_filter = parse_int(instance_id, "Instance ID")
    client_filter = str(client_ip or "").strip() or None
    start = parse_float(start_time, "start_time")
    end = parse_float(end_time, "end_time")
    page_offset = int(parse_int(offset, "offset", minimum=0, maximum=10_000_000) or 0)
    page_limit = clamp_limit(limit, default=80, maximum=200)

    records = extract_sd_records(state.messages)
    lifecycle: list[dict[str, Any]] = []
    clients_by_eventgroup: dict[int, set[str]] = defaultdict(set)
    action_groups = (
        ("SubscribeEventGroup", records["subscribes"]),
        ("StopSubscribeEventGroup", records["stop_subscribes"]),
        ("SubscribeEventGroupAck", records["subscribe_acks"]),
        ("SubscribeEventGroupNack", records["subscribe_nacks"]),
    )

    for action, action_records in action_groups:
        for record in action_records:
            eg_id = int(record.get("eventgroup_id", 0))
            evidence = record["evidence"]
            if record["service_id"] != sid:
                continue
            if eg_filter is not None and eg_id != eg_filter:
                continue
            if instance_filter is not None and record["instance_id"] != instance_filter:
                continue

            # Subscribe 的源地址是客户端；Ack/Nack 的目标地址是客户端。
            record_client = (
                record["ecu"] if action in {"SubscribeEventGroup", "StopSubscribeEventGroup"}
                else evidence.get("dst_ip")
            )
            if action == "SubscribeEventGroup" and record_client:
                clients_by_eventgroup[eg_id].add(str(record_client))
            if client_filter and record_client != client_filter:
                continue
            if not in_time_range(evidence, start, end):
                continue
            lifecycle.append({
                "action": action,
                "service_id": format_hex(sid),
                "instance_id": format_hex(int(record["instance_id"])),
                "eventgroup_id": format_hex(eg_id),
                "eventgroup_name": _eventgroup_name(state.registry, sid, eg_id),
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
    if eg_filter is not None:
        observed_eventgroups.add(eg_filter)

    # 普通 Notification 不携带 EventGroup ID，按项目现有的事件 ID 映射规则关联。
    for message in state.messages:
        if header_int(message, "service_id") in {SOMEIP_SD_SERVICE_ID}:
            continue
        if header_int(message, "service_id") != sid:
            continue
        if not is_notification(header_int(message, "message_type")):
            continue
        method_id = header_int(message, "method_id")
        evidence = build_message_evidence(message, kind="Notification")
        if not in_time_range(evidence, start, end):
            continue
        for eg_id in observed_eventgroups:
            if method_id not in {eg_id, eg_id | 0x8000}:
                continue
            if client_filter and client_filter not in clients_by_eventgroup.get(eg_id, set()):
                continue
            lifecycle.append({
                "action": "Notification",
                "service_id": format_hex(sid),
                "eventgroup_id": format_hex(eg_id),
                "eventgroup_name": _eventgroup_name(state.registry, sid, eg_id),
                "method_id": format_hex(method_id),
                "method_name": lookup_method_or_event_name(state.registry, sid, method_id),
                "server_ip": evidence.get("src_ip"),
                "destination_ip": evidence.get("dst_ip"),
                "evidence": evidence,
            })

    lifecycle.sort(key=_event_sort_key)
    page = lifecycle[page_offset:page_offset + page_limit]
    action_counts: dict[str, int] = defaultdict(int)
    for event in lifecycle:
        action_counts[event["action"]] += 1

    return {
        "service_id": format_hex(sid),
        "eventgroup_filter": format_hex(eg_filter) if eg_filter is not None else None,
        "instance_filter": format_hex(instance_filter) if instance_filter is not None else None,
        "client_filter": client_filter,
        "summary": {
            "event_count": len(lifecycle),
            "action_counts": dict(action_counts),
            "eventgroups": [format_hex(value) for value in sorted(observed_eventgroups)],
            "subscribing_clients": sorted({
                client for clients in clients_by_eventgroup.values() for client in clients
            }),
        },
        "association_rule": (
            "Notification 不直接携带 EventGroup ID；当前按 method_id 等于 "
            "eventgroup_id 或 eventgroup_id|0x8000 进行关联"
        ),
        "offset": page_offset,
        "next_offset": page_offset + len(page) if page_offset + len(page) < len(lifecycle) else None,
        "events": page,
    }


def _eventgroup_name(registry: Any, service_id: int, eventgroup_id: int) -> str | None:
    """安全读取 ARXML EventGroup 名称。"""
    try:
        return registry.lookup_eventgroup_name(service_id, eventgroup_id) if registry else None
    except Exception:
        return None


def _event_sort_key(event: dict[str, Any]) -> tuple[float, int, int]:
    """同一时间戳下按报文和 Entry 顺序稳定排序。"""
    evidence = event.get("evidence", {})
    return (
        float(evidence.get("timestamp_epoch") or 0.0),
        int(evidence.get("message_index") or 0),
        int(evidence.get("entry_index") or 0),
    )


__all__ = ["TOOL_DEFINITION", "get_subscription_timeline"]
