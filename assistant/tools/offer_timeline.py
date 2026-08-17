"""查询服务 Offer 生命周期时间线的 Tool。"""
from __future__ import annotations

from typing import Any

from analysis.sd_diagnostic import extract_sd_records
from assistant.tool_support import (
    clamp_limit,
    format_hex,
    in_time_range,
    lookup_service_name,
    parse_float,
    parse_int,
    require_session,
)

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_offer_timeline",
        "description": "查询指定服务的 Offer、StopOffer、发布 ECU、TTL 和时间顺序。",
        "parameters": {
            "type": "object",
            "properties": {
                "service_id": {"type": "string", "description": "必填 Service ID，例如 0x0A01。"},
                "instance_id": {"type": "string", "description": "可选 Instance ID。"},
                "start_time": {"type": "number", "description": "可选起始 epoch 秒。"},
                "end_time": {"type": "number", "description": "可选结束 epoch 秒。"},
                "offset": {"type": "integer", "description": "分页偏移，默认 0。"},
                "limit": {"type": "integer", "description": "返回数量，默认 50，最大 200。"},
            },
            "required": ["service_id"],
            "additionalProperties": False,
        },
    },
}


def get_offer_timeline(
    session_id: str,
    service_id: Any,
    instance_id: Any = None,
    start_time: Any = None,
    end_time: Any = None,
    offset: Any = None,
    limit: Any = None,
) -> dict[str, Any]:
    """返回按时间排序的 Offer 生命周期，周期 Offer 不做隐式合并。"""
    state = require_session(session_id)
    sid = int(parse_int(service_id, "Service ID", required=True))
    iid = parse_int(instance_id, "Instance ID")
    start = parse_float(start_time, "start_time")
    end = parse_float(end_time, "end_time")
    page_offset = int(parse_int(offset, "offset", minimum=0, maximum=10_000_000) or 0)
    page_limit = clamp_limit(limit, default=50, maximum=200)
    records = extract_sd_records(state.messages)

    timeline = []
    for action, items in (
        ("OfferService", records["offers"]),
        ("StopOfferService", records["stop_offers"]),
    ):
        for record in items:
            evidence = record["evidence"]
            if record["service_id"] != sid:
                continue
            if iid is not None and record["instance_id"] != iid:
                continue
            if not in_time_range(evidence, start, end):
                continue
            timeline.append({
                "action": action,
                "service_id": format_hex(sid),
                "instance_id": format_hex(record["instance_id"]),
                "server_ecu": record["ecu"],
                "ttl_seconds": record["ttl"],
                "major_version": record["major_version"],
                "minor_version": record["minor_version"],
                "evidence": evidence,
            })

    timeline.sort(key=lambda item: float(item["evidence"].get("timestamp_epoch") or 0.0))
    page = timeline[page_offset:page_offset + page_limit]
    offers = [item for item in timeline if item["action"] == "OfferService"]
    servers = sorted({item["server_ecu"] for item in offers})
    servers_by_instance: dict[str, set[str]] = {}
    for item in offers:
        servers_by_instance.setdefault(item["instance_id"], set()).add(item["server_ecu"])
    instance_sources = [
        {
            "instance_id": instance_id,
            "server_ecus": sorted(instance_servers),
            "offer_conflict": len(instance_servers) > 1,
        }
        for instance_id, instance_servers in sorted(servers_by_instance.items())
    ]
    return {
        "service_id": format_hex(sid),
        "service_name": lookup_service_name(state.registry, sid),
        "instance_filter": format_hex(iid) if iid is not None else None,
        "summary": {
            "offer_message_count": sum(item["action"] == "OfferService" for item in timeline),
            "stop_offer_message_count": sum(item["action"] == "StopOfferService" for item in timeline),
            "server_ecus": servers,
            "instances": instance_sources,
            "offer_conflict_observed": any(
                item["offer_conflict"] for item in instance_sources
            ),
        },
        "total_event_count": len(timeline),
        "offset": page_offset,
        "next_offset": page_offset + len(page) if page_offset + len(page) < len(timeline) else None,
        "events": page,
    }


__all__ = ["TOOL_DEFINITION", "get_offer_timeline"]
