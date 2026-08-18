"""AI Tool 共用的只读查询辅助函数。

各个独立Tool工具文件不要重复写解析、取值、格式化逻辑，全部抽到这里复用。
职责：会话获取、参数解析(十六进制/十进制/布尔、数值范围校验)、时间过滤、报文摘要格式化、ID与名称翻译、十六进制格式化。
全部是只读操作，不修改抓包数据；工具内部出现参数错误直接抛ValueError，上层会捕获作为tool结果返回给大模型。
"""
from __future__ import annotations

from typing import Any

from analysis.queries import ensure_session_queries
from analysis.queries.evidence import (
    build_message_evidence,
    format_hex,
    header_int,
    in_time_range,
    message_service_ids,
    structured_int,
)
# SOME/IP常量，事件ID掩码；把method_id里的event id剥离出来
from pcap_parsers.common import EVENT_ID_MASK, message_type_label
# 获取当前pcap解析会话session
from web.backend.handlers.analysis import get_session


def require_session(session_id: str) -> Any:
    """读取当前解析会话，不存在时抛出异常，工具调用时直接返回错误给大模型。"""
    state = get_session(session_id)
    if state is None:
        raise ValueError("解析会话不存在或已过期")
    return state


def require_queries(session_id: str) -> tuple[Any, Any]:
    """读取会话及其统一查询对象，旧会话缺少索引时自动补建一次。"""
    state = require_session(session_id)
    return state, ensure_session_queries(state)


def parse_int(
    value: Any,
    field_name: str,
    *,
    required: bool = False,
    minimum: int = 0,
    maximum: int = 0xFFFF,
) -> int | None:
    """
    解析AI工具调用传过来的整数参数，**同时支持十进制、0x开头十六进制字符串**，做数值范围校验。
    AI输出tool参数经常乱输出：字符串、"0x1234"、纯数字字符串、bool类型，全部做容错。
    :param value: AI输出的原始参数，可以是字符串/数字/None
    :param field_name: 参数名字，报错时提示给大模型
    :param required: 是否必填，True为空直接抛异常
    :param minimum/maximum: 数值上下限，SOME/IP ID大多是16位，默认0~0xFFFF
    :return: 解析后整数，非必填且为空返回None
    """
    if value is None or value == "":
        if required:
            raise ValueError(f"{field_name} 不能为空")
        return None
    # AI偶尔会错误输出布尔，bool是int子类，要提前拦截
    if isinstance(value, bool):
        raise ValueError(f"{field_name} 格式错误")
    try:
        # base=0自动识别0x十六进制、十进制
        parsed = int(str(value).strip(), 0)
    except (TypeError, ValueError) as exc:
        # 兼容模型输出带前导0的十进制，base=0对"00123"会报错，做降级兼容
        normalized = str(value).strip()
        try:
            parsed = int(normalized, 10) if normalized.isdigit() else None
        except ValueError:
            parsed = None
        if parsed is None:
            raise ValueError(f"{field_name} 应为十六进制或十进制整数") from exc
    # 校验数值区间，防止AI传超大数字越界
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{field_name} 必须在 {minimum} 到 {maximum} 之间")
    return parsed


def parse_float(value: Any, field_name: str) -> float | None:
    """解析可选浮点参数，用于pcap时间戳过滤，时间范围start_time/end_time。"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是数字") from exc


def clamp_limit(value: Any, *, default: int = 50, maximum: int = 200) -> int:
    """
    限制单次工具返回报文条数limit。
    如果抓包几万条报文，AI要求返回全部报文会直接撑爆LLM上下文，强制做上限截断。
    不传limit使用默认50，最大不能超过200。
    """
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
    """
    解析布尔参数，兼容AI输出多种形式：true/false字符串、"1"/"0"、"yes"/"no"、原生bool。
    AI不会严格输出JSON bool，经常输出字符串，做兼容转换。
    """
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


def compact_message(message: dict[str, Any], registry: Any = None) -> dict[str, Any]:
    """
    生成**给大模型阅读的精简报文摘要**。
    原始pcap报文对象字段极多，全部传给LLM会浪费token；只提取AI需要的关键字段。
    同时带上evidence证据（message_index、frame_index等），满足system prompt强制证据要求。
    SD报文的entries最多返回12条，超过标记截断，避免返回过多数据。
    :param registry: ARXML注册表，可以把service_id/method_id翻译成可读服务名、方法名
    """
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
                "service_id": format_hex(structured_int(entry.get("service_id"))),
                "instance_id": format_hex(structured_int(entry.get("instance_id"))),
                "eventgroup_id": (
                    format_hex(structured_int(entry.get("eventgroup_id")))
                    if entry.get("eventgroup_id") is not None else None
                ),
            }
            for entry in entries[:12]
        ]
        summary["sd_entries_truncated"] = len(entries) > 12
    return summary


def lookup_service_name(registry: Any, service_id: int) -> str | None:
    """根据service_id从ARXML注册表查找服务名称；注册表不存在或者查找异常返回None，不崩溃。"""
    try:
        return registry.lookup_service_name(service_id) if registry else None
    except Exception:
        return None


def lookup_method_or_event_name(
    registry: Any,
    service_id: int,
    method_id: int,
) -> str | None:
    """
    根据service_id + method_id查找名字。
    SOME/IP中Event通知和Method共用ID空间，需要先尝试Event，再尝试Method。
    EVENT_ID_MASK掩码剥离高位，兼容event id编码规则。
    """
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
