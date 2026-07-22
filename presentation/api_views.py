"""Frontend-facing message view models.

The core pipeline returns internal enriched messages.  This module converts
those messages into the shapes consumed by Vue:

- list summaries for the message table
- one-message detail payloads
- raw protocol trees and human-readable message kind labels
"""
from __future__ import annotations

from typing import Any

from pcap_parsers.common import (
    EVENT_ID_MASK,
    SOMEIP_SD_SERVICE_ID,
    message_type_label,
)
from presentation.message_view import build_message_raw_view


def render_messages_for_frontend(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach frontend-only fields to parsed messages.

    The returned list contains shallow copies.  Callers can safely keep the core
    pipeline output as a parser artifact while handing this rendered shape to
    the Web session and frontend.
    """
    rendered: list[dict[str, Any]] = []
    for raw_msg in messages:
        msg = dict(raw_msg)
        msg["raw_view"] = build_message_raw_view(msg).to_dict()
        msg["message_kind"] = resolve_message_kind(msg)
        rendered.append(msg)
    return rendered


def build_message_summaries(
    messages: list[dict[str, Any]],
    registry: Any = None,
) -> list[dict[str, Any]]:
    """Build compact rows for the frontend message table."""
    return [
        {
            "index": m["index"],
            "frame_index": m["frame_index"],
            "service_id": m["header"]["service_id"]["hex"],
            "service_name": _resolve_svc_name(registry, m),
            "method_id": m["header"]["method_id"]["hex"],
            "method_name": _resolve_method_name(registry, m),
            "message_type": m["header"]["message_type"]["hex"],
            "message_kind": m.get("message_kind", "?"),
            "transport": m["transport"],
            "payload_length": m["payload_length"],
            "parse_status": m.get("parse_status", "unresolved"),
        }
        for m in messages
    ]


def build_message_detail(messages: list[dict[str, Any]], index: int) -> dict | None:
    """Return the full frontend detail object for a selected message index."""
    for m in messages:
        if m["index"] == index:
            return {
                "index": m["index"],
                "frame_index": m["frame_index"],
                "service_id": m["header"]["service_id"]["hex"],
                "method_id": m["header"]["method_id"]["hex"],
                "message_type": m["header"]["message_type"]["hex"],
                "message_kind": m.get("message_kind", "?"),
                "transport": m["transport"],
                "payload_length": m["payload_length"],
                "payload_hex": m["payload_hex"],
                "raw_header_hex": m["raw_header_hex"],
                "parse_status": m.get("parse_status", "unresolved"),
                "parsed": m.get("parsed"),
                "raw_view": m.get("raw_view"),
            }
    return None


def resolve_message_kind(msg: dict[str, Any]) -> str:
    """Return a readable kind label for regular SOME/IP and SD messages."""
    header = msg.get("header", {})
    srv_id = header.get("service_id", {}).get("dec", 0)
    if srv_id != SOMEIP_SD_SERVICE_ID:
        return message_type_label(header.get("message_type", {}).get("dec", 0))

    entries = msg.get("sd", {}).get("entries", [])
    if not entries:
        return "SD"

    labels: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        label = _sd_entry_kind_label(entry.get("type", ""))
        if label not in seen:
            labels.append(label)
            seen.add(label)
    return "/".join(labels) if labels else "SD"


def _resolve_svc_name(registry: Any, msg: dict[str, Any]) -> str:
    try:
        if registry:
            sid = msg["header"]["service_id"]["dec"]
            return registry.lookup_service_name(sid) or ""
    except Exception:
        pass
    return ""


def _resolve_method_name(registry: Any, msg: dict[str, Any]) -> str:
    try:
        if registry:
            sid = msg["header"]["service_id"]["dec"]
            mid = msg["header"]["method_id"]["dec"]

            # Notification event IDs often carry the 0x8000 event bit.  Try the
            # masked value first because ARXML deployments usually store bare IDs.
            n = registry.lookup_event_name(sid, mid & EVENT_ID_MASK)
            if n:
                return n
            n = registry.lookup_method_name(sid, mid & EVENT_ID_MASK)
            if n:
                return n

            # Fallback to the exact wire value for nonstandard ARXML exports.
            n = registry.lookup_event_name(sid, mid)
            if n:
                return n
            n = registry.lookup_method_name(sid, mid)
            if n:
                return n
    except Exception:
        pass
    return ""


def _sd_entry_kind_label(entry_type: str) -> str:
    if entry_type in {"OfferService", "StopOfferService"}:
        return "Offer"
    if entry_type == "SubscribeEventGroup":
        return "Subscribe"
    if entry_type in {
        "SubscribeEventGroupAck",
        "SubscribeEventgroupAck",
        "SubscribeEventGroupNack",
    }:
        return "SubscribeAck"
    return entry_type or "SD"
