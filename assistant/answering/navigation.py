"""从 Tool 结果中提取并校验前端可用的导航证据。"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

_MAX_MESSAGE_LINKS = 8
_MAX_EVENTGROUP_LINKS = 4
_MAX_SERVICE_LINKS = 6


def collect_navigation_links(
    tool_name: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    """生成有上限的结构化链接，避免前端解析模型自然语言。

    Tool 结果中的证据是可信结构化数据。这里提取消息、Service 和 EventGroup
    标识，并保留工具参数中的信号时间范围；不把完整 Tool 结果返回浏览器。
    """
    return _collect_navigation_links(tool_name, arguments, result, include_arguments=True)


def collect_verified_navigation_links(
    tool_name: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    """仅返回可由本轮 Tool 结果验证的链接。

    普通证据区允许保留用户明确查询的目标；模型回答中的 Markdown 链接要求
    更严格，因此 Service、EventGroup 和 Message 必须实际出现在 Tool 结果中。
    信号页参数由已成功执行的统计/时间线查询共同验证。
    """
    return _collect_navigation_links(tool_name, arguments, result, include_arguments=False)


def _collect_navigation_links(
    tool_name: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
    *,
    include_arguments: bool,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    eventgroups: list[dict[str, Any]] = []
    services: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    requested_service_id = _parse_id(arguments.get("service_id"))

    def add(link: dict[str, Any], key: tuple[Any, ...]) -> None:
        if key in seen:
            return
        seen.add(key)
        if link["kind"] == "message":
            messages.append(link)
        elif link["kind"] == "eventgroup":
            eventgroups.append(link)
        elif link["kind"] == "service":
            services.append(link)

    def walk(value: Any, service_context: int | None = None) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item, service_context)
            return
        if not isinstance(value, dict):
            return

        service_id = _parse_id(value.get("service_id"))
        if service_id is None:
            service_id = service_context
        elif service_id != 0xFFFF and (
            requested_service_id is None or service_id == requested_service_id
        ):
            add({
                "kind": "service",
                "label": f"Service 0x{service_id:04X}",
                "service_id": service_id,
            }, ("service", service_id))

        message_index = _parse_int(value.get("message_index"))
        frame_index = _parse_int(value.get("frame_index"))
        if message_index is not None:
            label = f"Message {message_index}"
            if frame_index is not None:
                label += f" / Frame {frame_index}"
            add({
                "kind": "message",
                "label": label,
                "message_index": message_index,
                "frame_index": frame_index,
            }, ("message", message_index))

        eventgroup_id = _parse_id(value.get("eventgroup_id"))
        if (
            service_id is not None
            and eventgroup_id is not None
            and (
                requested_service_id is None
                or service_id == requested_service_id
            )
        ):
            add({
                "kind": "eventgroup",
                "label": f"EventGroup 0x{eventgroup_id:04X}",
                "service_id": service_id,
                "eventgroup_id": eventgroup_id,
            }, ("eventgroup", service_id, eventgroup_id))

        for child in value.values():
            walk(child, service_id)

    walk(result)
    if include_arguments:
        _collect_argument_links(arguments, add)
    signal_link = _signal_link(tool_name, arguments)
    if not include_arguments and (not result or "error" in result):
        signal_link = None
    links = (
        messages[:_MAX_MESSAGE_LINKS]
        + eventgroups[:_MAX_EVENTGROUP_LINKS]
        + services[:_MAX_SERVICE_LINKS]
    )
    if signal_link:
        links.append(signal_link)
    return links


_MARKDOWN_SOMEIP_LINK_RE = re.compile(
    r"\[([^\]\n]+)\]\((#someip-(?:message|service|eventgroup|signal)[^)\s]+)\)",
    re.IGNORECASE,
)


def validate_answer_navigation_links(
    answer: str,
    verified_links: list[dict[str, Any]],
) -> tuple[str, int]:
    """删除无法由本轮 Tool 结果验证的 SOME/IP Markdown 链接。

    这里只处理应用内部的 ``#someip-*`` 导航，普通外部 Markdown 链接保持不变。
    无效链接会退化为可读标签，不把模型生成的未知目标交给前端执行。
    """
    allowed = {_link_identity(link) for link in verified_links}
    allowed.discard(None)
    removed = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal removed
        identity = _target_identity(match.group(2))
        if identity is not None and identity in allowed:
            return match.group(0)
        removed += 1
        return match.group(1)

    return _MARKDOWN_SOMEIP_LINK_RE.sub(replace, answer), removed


def _link_identity(link: dict[str, Any]) -> tuple[Any, ...] | None:
    kind = link.get("kind")
    if kind == "message":
        index = _parse_int(link.get("message_index"))
        return ("message", index) if index is not None else None
    if kind == "service":
        service_id = _parse_id(link.get("service_id"))
        return ("service", service_id) if service_id is not None else None
    if kind == "eventgroup":
        service_id = _parse_id(link.get("service_id"))
        eventgroup_id = _parse_id(link.get("eventgroup_id"))
        if service_id is not None and eventgroup_id is not None:
            return ("eventgroup", service_id, eventgroup_id)
        return None
    if kind == "signal":
        service_id = _parse_id(link.get("service_id"))
        if service_id is None:
            return None
        return (
            "signal",
            service_id,
            _parse_id(link.get("event_id")),
            str(link.get("field_path") or ""),
            _parse_float(link.get("start_time")),
            _parse_float(link.get("end_time")),
        )
    return None


def _target_identity(target: str) -> tuple[Any, ...] | None:
    message = re.fullmatch(r"#someip-message-(\d+)", target, re.IGNORECASE)
    if message:
        return ("message", int(message.group(1)))
    service = re.fullmatch(
        r"#someip-service-(0x[0-9a-f]+|\d+)", target, re.IGNORECASE
    )
    if service:
        return ("service", _parse_id(service.group(1)))
    eventgroup = re.fullmatch(
        r"#someip-eventgroup-(0x[0-9a-f]+|\d+)-(0x[0-9a-f]+|\d+)",
        target,
        re.IGNORECASE,
    )
    if eventgroup:
        return (
            "eventgroup",
            _parse_id(eventgroup.group(1)),
            _parse_id(eventgroup.group(2)),
        )
    if not target.lower().startswith("#someip-signal?"):
        return None
    parsed = urlsplit(target[1:])
    query = parse_qs(parsed.query, keep_blank_values=True)
    service_id = _parse_id(_first(query, "service"))
    if parsed.path.lower() != "someip-signal" or service_id is None:
        return None
    return (
        "signal",
        service_id,
        _parse_id(_first(query, "event")),
        str(_first(query, "field") or ""),
        _parse_float(_first(query, "start")),
        _parse_float(_first(query, "end")),
    )


def _first(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    return values[0] if values else None


def _collect_argument_links(arguments: dict[str, Any], add: Any) -> None:
    """即使 Tool 没有匹配结果，也保留用户明确查询的 Service/EventGroup。"""
    service_id = _parse_id(arguments.get("service_id"))
    if service_id is None:
        return
    add({
        "kind": "service",
        "label": f"Service 0x{service_id:04X}",
        "service_id": service_id,
    }, ("service", service_id))
    eventgroup_id = _parse_id(arguments.get("eventgroup_id"))
    if eventgroup_id is not None:
        add({
            "kind": "eventgroup",
            "label": f"EventGroup 0x{eventgroup_id:04X}",
            "service_id": service_id,
            "eventgroup_id": eventgroup_id,
        }, ("eventgroup", service_id, eventgroup_id))


def _signal_link(
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any] | None:
    """把通知统计或显式时间范围转换为信号时序定位参数。"""
    service_id = _parse_id(arguments.get("service_id"))
    raw_event_id = arguments.get("method_id")
    if raw_event_id is None or raw_event_id == "":
        raw_event_id = arguments.get("eventgroup_id")
    event_id = _parse_id(raw_event_id)
    start_time = _parse_float(arguments.get("start_time"))
    end_time = _parse_float(arguments.get("end_time"))
    field_path = str(arguments.get("field_path") or "").strip() or None
    supports_signal = tool_name in {
        "get_notification_statistics",
        "get_subscription_timeline",
    }
    if service_id is None or not supports_signal:
        return None
    if event_id is None and start_time is None and end_time is None:
        return None
    return {
        "kind": "signal",
        "label": "Open signal timing",
        "service_id": service_id,
        "event_id": event_id,
        "field_path": field_path,
        "start_time": start_time,
        "end_time": end_time,
    }


def _parse_id(value: Any) -> int | None:
    if isinstance(value, dict):
        value = value.get("dec", value.get("hex"))
    parsed = _parse_int(value)
    return parsed if parsed is not None and 0 <= parsed <= 0xFFFF else None


def _parse_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip(), 0)
    except (TypeError, ValueError):
        # 某些模型可能把十进制 ID 写成带前导零的字符串，base=0 不接受该形式。
        try:
            return int(str(value).strip(), 10)
        except (TypeError, ValueError):
            return None


def _parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "collect_navigation_links",
    "collect_verified_navigation_links",
    "validate_answer_navigation_links",
]
