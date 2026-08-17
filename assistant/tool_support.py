"""AI Tool 共用的只读查询辅助函数。

具体 Tool 保持一个文件一个功能；会话读取、ID 解析和证据格式化集中在这里，
避免每个 Tool 各自实现一套容易产生差异的基础逻辑。
"""
from __future__ import annotations

from typing import Any

from analysis.sd_diagnostic import build_message_evidence
from pcap_parsers.common import EVENT_ID_MASK, message_type_label
from web.backend.handlers.analysis import get_session


def require_session(session_id: str) -> Any:
    """读取当前解析会话，不存在时给模型返回明确错误。"""
    state = get_session(session_id)
    if state is None:
        raise ValueError("解析会话不存在或已过期")
    return state


def parse_int(
    value: Any,
    field_name: str,
    *,
    required: bool = False,
    minimum: int = 0,
    maximum: int = 0xFFFF,
) -> int | None:
    """同时接受十六进制字符串和十进制整数，并执行统一范围校验。"""
    if value is None or value == "":
        if required:
            raise ValueError(f"{field_name} 不能为空")
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field_name} 格式错误")
    try:
        parsed = int(str(value).strip(), 0)
    except (TypeError, ValueError) as exc:
        # 模型可能生成带前导零的十进制字符串，Python 的 base=0 不接受这种形式。
        normalized = str(value).strip()
        try:
            parsed = int(normalized, 10) if normalized.isdigit() else None
        except ValueError:
            parsed = None
        if parsed is None:
            raise ValueError(f"{field_name} 应为十六进制或十进制整数") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{field_name} 必须在 {minimum} 到 {maximum} 之间")
    return parsed


def parse_float(value: Any, field_name: str) -> float | None:
    """解析可选浮点参数，主要用于 PCAP 时间范围过滤。"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是数字") from exc


def clamp_limit(value: Any, *, default: int = 50, maximum: int = 200) -> int:
    """限制单次 Tool 返回数量，避免大抓包占满模型上下文。"""
    if value is None or value == "":
        return default
    parsed = parse_int(
        value,
        "limit",
        required=True,
        minimum=1,
        maximum=maximum,
    )
    return int(parsed)


def parse_bool(value: Any, field_name: str, *, default: bool = False) -> bool:
    """兼容模型可能生成的布尔值或 true/false 字符串。"""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"{field_name} 必须是布尔值")


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


def header_int(message: dict[str, Any], field: str) -> int:
    """读取标准化 SOME/IP Header 字段的十进制真值。"""
    value = message.get("header", {}).get(field, {})
    return int(value.get("dec", 0)) if isinstance(value, dict) else int(value or 0)


def message_service_ids(message: dict[str, Any]) -> set[int]:
    """返回消息涉及的服务 ID，SD 消息会展开其所有 Entry。"""
    service_ids = {header_int(message, "service_id")}
    for entry in message.get("sd", {}).get("entries", []):
        value = entry.get("service_id")
        if isinstance(value, dict) and isinstance(value.get("dec"), int):
            service_ids.add(value["dec"])
    return service_ids


def compact_message(message: dict[str, Any], registry: Any = None) -> dict[str, Any]:
    """生成适合模型读取的紧凑报文摘要，并保留可点击证据。"""
    service_id = header_int(message, "service_id")
    method_id = header_int(message, "method_id")
    message_type = header_int(message, "message_type")
    summary = {
        "evidence": build_message_evidence(message),
        "service_id": format_hex(service_id),
        "service_name": lookup_service_name(registry, service_id),
        "method_id": format_hex(method_id),
        "method_name": lookup_method_or_event_name(registry, service_id, method_id),
        "message_type": f"0x{message_type:02X}",
        "message_type_name": message.get("message_kind") or message_type_label(message_type),
        "payload_length": int(message.get("payload_length", 0)),
        "parse_status": message.get("parse_status", "unresolved"),
    }
    entries = message.get("sd", {}).get("entries", [])
    if entries:
        summary["sd_entries"] = [
            {
                "type": entry.get("type"),
                "service_id": format_hex(_structured_int(entry.get("service_id"))),
                "instance_id": format_hex(_structured_int(entry.get("instance_id"))),
                "eventgroup_id": (
                    format_hex(_structured_int(entry.get("eventgroup_id")))
                    if entry.get("eventgroup_id") is not None else None
                ),
            }
            for entry in entries[:12]
        ]
        summary["sd_entries_truncated"] = len(entries) > 12
    return summary


def format_hex(value: int, width: int = 4) -> str:
    """统一输出大写并补零的十六进制 ID。"""
    return f"0x{value:0{width}X}"


def lookup_service_name(registry: Any, service_id: int) -> str | None:
    """安全读取 ARXML 服务名称。"""
    try:
        return registry.lookup_service_name(service_id) if registry else None
    except Exception:
        return None


def lookup_method_or_event_name(
    registry: Any,
    service_id: int,
    method_id: int,
) -> str | None:
    """按事件优先、方法其次的顺序解析 Method/Event 名称。"""
    if not registry:
        return None
    try:
        event_name = registry.lookup_event_name(service_id, method_id & EVENT_ID_MASK)
        if event_name:
            return event_name
        event_name = registry.lookup_event_name(service_id, method_id)
        if event_name:
            return event_name
        method_name = registry.lookup_method_name(service_id, method_id & EVENT_ID_MASK)
        if method_name:
            return method_name
        return registry.lookup_method_name(service_id, method_id)
    except Exception:
        return None


def _structured_int(value: Any) -> int:
    """读取 parser 输出的 {dec, hex} 数值或普通整数。"""
    if isinstance(value, dict):
        return int(value.get("dec", 0))
    return int(value or 0)
