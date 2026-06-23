"""
信号时序分析 API — Web 胶水层。

从会话缓存取数据 → 调 analysis 模块做提取/检测 → 格式化返回。
"""
from __future__ import annotations
from typing import Any

from analysis.signal_utils import (
    collect_leaf_paths,
    detect_transitions,
    get_field_value,
)
from pcap_parsers.common import (
    EVENT_ID_MASK,
    SOMEIP_SD_SERVICE_ID,
    is_notification,
)
from web.backend.handlers.analysis import get_session

_SD_SERVICE_ID = SOMEIP_SD_SERVICE_ID


# ═══════════════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════════════

def get_signal_meta(session_id: str) -> list[dict[str, Any]]:
    """返回会话中可绘制信号的三级级联数据（服务→事件→字段路径）。"""
    state = get_session(session_id)
    if state is None:
        return []

    svc_map: dict[int, dict[str, Any]] = {}

    for msg in state.messages:
        header = msg.get("header", {})
        srv_id = header.get("service_id", {}).get("dec", 0)
        msg_type = header.get("message_type", {}).get("dec", 0)
        method_id = header.get("method_id", {}).get("dec", 0)

        if srv_id == _SD_SERVICE_ID:
            continue
        if not is_notification(msg_type):
            continue
        if msg.get("parse_status") != "ok":
            continue
        parsed = msg.get("parsed")
        if not parsed:
            continue

        if srv_id not in svc_map:
            svc_map[srv_id] = {
                "service_id": srv_id,
                "service_id_hex": header["service_id"]["hex"],
                "service_name": _svc_name(srv_id, state),
                "events": {},
            }

        event_map = svc_map[srv_id]["events"]
        if method_id not in event_map:
            fields = collect_leaf_paths(parsed)
            if fields:
                event_map[method_id] = {
                    "event_id": method_id,
                    "event_id_hex": header["method_id"]["hex"],
                    "event_name": _evt_name(state, srv_id, method_id),
                    "fields": fields,
                }

    result: list[dict[str, Any]] = []
    for srv_id in sorted(svc_map.keys()):
        entry = svc_map[srv_id]
        ev_list = sorted(entry["events"].values(), key=lambda e: e["event_id"])
        entry["events"] = ev_list
        result.append(entry)

    return result


def get_signal_data(
    session_id: str,
    service_id: int,
    event_id: int,
    field_path: str,
) -> dict[str, Any] | None:
    """从会话缓存中提取指定字段的时序数据 + 跳变点。"""
    state = get_session(session_id)
    if state is None:
        return None

    # 支持多字段（逗号分隔）
    field_paths = [fp.strip() for fp in field_path.split(",") if fp.strip()]
    if not field_paths:
        return None

    # 筛选候选报文（与字段无关，先筛出所有匹配的 notification）
    candidates: list[dict[str, Any]] = []
    for msg in state.messages:
        header = msg.get("header", {})
        srv_id = header.get("service_id", {}).get("dec", 0)
        msg_type = header.get("message_type", {}).get("dec", 0)
        mid = header.get("method_id", {}).get("dec", 0)

        if srv_id != service_id:
            continue
        if not is_notification(msg_type):
            continue
        if msg.get("parse_status") != "ok":
            continue
        if not msg.get("parsed"):
            continue
        if mid != event_id and (mid & EVENT_ID_MASK) != event_id:
            continue

        candidates.append(msg)

    if not candidates:
        return _empty_multi(service_id, event_id, field_paths)

    candidates.sort(key=lambda m: m.get("frame_index", 0))

    # 对每个字段分别提取
    fields_data: list[dict[str, Any]] = []
    for fp in field_paths:
        path_parts = [p for p in fp.split(".") if p]
        points: list[dict[str, Any]] = []
        for seq, msg in enumerate(candidates, 1):
            parsed = msg.get("parsed")
            if not parsed:
                continue
            value = get_field_value(parsed, path_parts)
            if value is None:
                continue
            points.append({
                "seq": seq,
                "frame_index": msg.get("frame_index", 0),
                "value": value,
            })
        fields_data.append({
            "field_path": fp,
            "points": points,
            "transitions": detect_transitions(points),
        })

    return {
        "service_id": service_id,
        "event_id": event_id,
        "fields": fields_data,
    }


def _empty_multi(sid: int, eid: int, fps: list[str]) -> dict[str, Any]:
    return {
        "service_id": sid, "event_id": eid,
        "fields": [{"field_path": fp, "points": [], "transitions": []} for fp in fps],
    }


def _svc_name(srv_id: int, state: Any) -> str:
    try:
        reg = getattr(state, "registry", None)
        if reg:
            n = reg.lookup_service_name(srv_id)
            if n:
                return n
    except Exception:
        pass
    return ""


def _evt_name(state: Any, srv_id: int, event_id: int) -> str:
    try:
        reg = getattr(state, "registry", None)
        if reg:
            # notification event_id 带 0x8000 高位，先去掉再查
            n = reg.lookup_event_name(srv_id, event_id & 0x7FFF)
            if n:
                return n
            n = reg.lookup_event_name(srv_id, event_id)
            if n:
                return n
    except Exception:
        pass
    return ""
