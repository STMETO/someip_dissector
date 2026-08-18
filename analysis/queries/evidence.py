"""统一查询层使用的报文取值和证据格式化函数。"""
from __future__ import annotations

from typing import Any


def structured_int(value: Any) -> int:
    """读取 parser 输出的 ``{dec, hex}`` 数值或普通整数。"""
    if isinstance(value, dict):
        return int(value.get("dec", 0))
    return int(value or 0)


def header_int(message: dict[str, Any], field: str) -> int:
    """读取标准化 SOME/IP Header 字段的十进制真值。"""
    return structured_int(message.get("header", {}).get(field))


def message_service_ids(message: dict[str, Any]) -> set[int]:
    """返回消息涉及的服务 ID，SD 消息会包含所有 Entry 的服务 ID。"""
    service_ids = {header_int(message, "service_id")}
    for entry in message.get("sd", {}).get("entries", []):
        if entry.get("service_id") is not None:
            service_ids.add(structured_int(entry.get("service_id")))
    return service_ids


def build_message_evidence(
    message: dict[str, Any],
    *,
    kind: str = "",
    entry_index: int | None = None,
) -> dict[str, Any]:
    """生成页面跳转和 AI 回答共同使用的最小报文证据。"""
    evidence = {
        "message_index": message.get("index"),
        "frame_index": message.get("frame_index"),
        "timestamp_epoch": message.get("timestamp_epoch", 0.0),
        "timestamp_iso": message.get("timestamp_iso", ""),
        "transport": message.get("transport", ""),
        "src_ip": message.get("src_ip"),
        "src_port": message.get("src_port"),
        "dst_ip": message.get("dst_ip"),
        "dst_port": message.get("dst_port"),
        "kind": kind or message.get("message_kind", ""),
    }
    if entry_index is not None:
        evidence["entry_index"] = entry_index
    return evidence


def in_time_range(
    message_or_evidence: dict[str, Any],
    start_time: float | None,
    end_time: float | None,
) -> bool:
    """判断消息或证据是否位于闭区间时间范围内。"""
    timestamp = float(message_or_evidence.get("timestamp_epoch") or 0.0)
    if start_time is not None and timestamp < start_time:
        return False
    if end_time is not None and timestamp > end_time:
        return False
    return True


def format_hex(value: int, width: int = 4) -> str:
    """统一输出大写并补零的十六进制 ID。"""
    return f"0x{value:0{width}X}"


def event_sort_key(event: dict[str, Any]) -> tuple[float, int, int]:
    """同一时间戳下按消息和 SD Entry 顺序稳定排序。"""
    evidence = event.get("evidence", {})
    return (
        float(evidence.get("timestamp_epoch") or 0.0),
        int(evidence.get("message_index") or 0),
        int(evidence.get("entry_index") or 0),
    )


__all__ = [
    "build_message_evidence",
    "event_sort_key",
    "format_hex",
    "header_int",
    "in_time_range",
    "message_service_ids",
    "structured_int",
]
