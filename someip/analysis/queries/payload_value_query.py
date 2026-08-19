"""反序列化 Payload 字段值检索。"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any

from someip.analysis.signal_utils import find_field_node

from .evidence import build_message_evidence, format_hex, header_int, in_time_range
from .message_query import MessageQuery

_MAX_CACHED_PATHS = 32


class PayloadValueQuery:
    """按字段路径建立有界懒索引，避免 Tool 层重复遍历解析树。"""

    def __init__(self, messages: MessageQuery):
        self._messages = messages
        self._path_cache: OrderedDict[
            str, tuple[tuple[dict[str, Any], dict[str, Any]], ...]
        ] = OrderedDict()

    def search(
        self,
        field_path: str,
        *,
        service_id: int | None = None,
        method_id: int | None = None,
        exact_value: Any = None,
        text_contains: str | None = None,
        minimum: float | None = None,
        maximum: float | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        offset: int = 0,
        limit: int = 80,
    ) -> dict[str, Any]:
        """检索字段值；字符串、布尔和数值均可精确匹配。"""
        path = field_path.strip()
        if not path:
            raise ValueError("field_path 不能为空")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError("minimum 不能大于 maximum")
        contains = text_contains.casefold() if text_contains else None

        matched: list[dict[str, Any]] = []
        for message, node in self._entries(path):
            if service_id is not None and header_int(message, "service_id") != service_id:
                continue
            if method_id is not None and header_int(message, "method_id") != method_id:
                continue
            if not in_time_range(message, start_time, end_time):
                continue
            value = node.get("value")
            if exact_value is not None and not _values_equal(value, exact_value):
                continue
            if contains is not None and contains not in str(value).casefold():
                continue
            numeric = _to_number(value)
            if minimum is not None and (numeric is None or numeric < minimum):
                continue
            if maximum is not None and (numeric is None or numeric > maximum):
                continue
            matched.append({
                "service_id": format_hex(header_int(message, "service_id")),
                "method_id": format_hex(header_int(message, "method_id")),
                "field_path": path,
                "field": {
                    "name": node.get("name"),
                    "type": node.get("type"),
                    "value": _compact_value(value),
                    "byte_size": node.get("byte_size"),
                    "offset": node.get("offset"),
                },
                "evidence": build_message_evidence(message),
            })

        page = matched[offset:offset + limit]
        return {
            "field_path": path,
            "filters": {
                "service_id": format_hex(service_id) if service_id is not None else None,
                "method_id": format_hex(method_id) if method_id is not None else None,
                "exact_value": exact_value,
                "text_contains": text_contains,
                "minimum": minimum,
                "maximum": maximum,
                "start_time": start_time,
                "end_time": end_time,
            },
            "matched_message_count": len(matched),
            "offset": offset,
            "next_offset": offset + len(page) if offset + len(page) < len(matched) else None,
            "matches": page,
        }

    def _entries(
        self,
        field_path: str,
    ) -> tuple[tuple[dict[str, Any], dict[str, Any]], ...]:
        cached = self._path_cache.get(field_path)
        if cached is not None:
            self._path_cache.move_to_end(field_path)
            return cached

        parts = [part for part in field_path.split(".") if part]
        entries: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for message in self._messages.all:
            parsed = message.get("parsed")
            if not isinstance(parsed, dict):
                continue
            node = find_field_node(parsed, parts)
            if node is not None and "value" in node:
                entries.append((message, node))
        frozen = tuple(entries)
        self._path_cache[field_path] = frozen
        if len(self._path_cache) > _MAX_CACHED_PATHS:
            self._path_cache.popitem(last=False)
        return frozen


def _values_equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool):
        if isinstance(expected, str):
            normalized = expected.strip().casefold()
            return normalized in {"true", "1"} if actual else normalized in {"false", "0"}
        return actual is expected
    if isinstance(expected, bool):
        return actual is expected
    actual_number = _to_number(actual)
    expected_number = _to_number(expected)
    if actual_number is not None and expected_number is not None:
        return actual_number == expected_number
    return str(actual) == str(expected)


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compact_value(value: Any) -> Any:
    """限制异常长字符串，避免单个字段挤占模型上下文。"""
    if isinstance(value, str) and len(value) > 512:
        return value[:512] + "..."
    return value


__all__ = ["PayloadValueQuery"]
