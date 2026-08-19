"""基于一次性只读索引的 SOME/IP 报文查询。"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from someip.pcap_parsers.common import SOMEIP_SD_SERVICE_ID, is_notification, message_type_label

from .evidence import (
    build_message_evidence,
    header_int,
    in_time_range,
    message_service_ids,
)


@dataclass(frozen=True)
class MessageSearchResult:
    """分页消息查询结果；消息对象仍引用完整解析结果，不复制 Payload。"""

    total: int
    messages: tuple[dict[str, Any], ...]
    offset: int
    next_offset: int | None


class MessageQuery:
    """为一份解析会话建立消息索引，并提供统一过滤和按索引读取。"""

    def __init__(self, messages: list[dict[str, Any]]):
        self._messages = tuple(messages)
        self._by_index: dict[int, dict[str, Any]] = {}
        service: dict[int, list[dict[str, Any]]] = defaultdict(list)
        method: dict[int, list[dict[str, Any]]] = defaultdict(list)
        message_type: dict[int, list[dict[str, Any]]] = defaultdict(list)
        src_ip: dict[str, list[dict[str, Any]]] = defaultdict(list)
        dst_ip: dict[str, list[dict[str, Any]]] = defaultdict(list)
        parse_status: dict[str, list[dict[str, Any]]] = defaultdict(list)
        sd_entry_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
        notifications: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        notifications_by_service: dict[int, list[dict[str, Any]]] = defaultdict(list)
        all_notifications: list[dict[str, Any]] = []

        timestamps: list[float] = []
        for message in self._messages:
            index = int(message.get("index", -1))
            if index >= 0:
                self._by_index[index] = message
            for service_id in message_service_ids(message):
                service[service_id].append(message)
            method_id = header_int(message, "method_id")
            type_id = header_int(message, "message_type")
            method[method_id].append(message)
            message_type[type_id].append(message)
            src_ip[str(message.get("src_ip") or "")].append(message)
            dst_ip[str(message.get("dst_ip") or "")].append(message)
            parse_status[str(message.get("parse_status", "unresolved")).casefold()].append(message)
            kind[str(message.get("message_kind", "")).casefold()].append(message)
            for entry_type in {
                str(entry.get("type", "")).casefold()
                for entry in message.get("sd", {}).get("entries", [])
                if entry.get("type")
            }:
                sd_entry_type[entry_type].append(message)

            wire_service_id = header_int(message, "service_id")
            if wire_service_id != SOMEIP_SD_SERVICE_ID and is_notification(type_id):
                notifications[(wire_service_id, method_id)].append(message)
                notifications_by_service[wire_service_id].append(message)
                all_notifications.append(message)
            timestamps.append(float(message.get("timestamp_epoch") or 0.0))

        self._by_service = _freeze_index(service)
        self._by_method = _freeze_index(method)
        self._by_message_type = _freeze_index(message_type)
        self._by_src_ip = _freeze_index(src_ip)
        self._by_dst_ip = _freeze_index(dst_ip)
        self._by_parse_status = _freeze_index(parse_status)
        self._by_sd_entry_type = _freeze_index(sd_entry_type)
        self._by_kind = _freeze_index(kind)
        self._notifications = _freeze_index(notifications)
        self._notifications_by_service = _freeze_index(notifications_by_service)
        self._all_notifications = tuple(all_notifications)
        self._timestamps = tuple(timestamps)
        self._time_ordered = all(
            earlier <= later for earlier, later in zip(timestamps, timestamps[1:])
        )

    @property
    def all(self) -> tuple[dict[str, Any], ...]:
        """返回会话内按抓包顺序排列的全部消息引用。"""
        return self._messages

    @property
    def service_ids(self) -> tuple[int, ...]:
        """返回抓包消息和 SD Entry 中观察到的全部 Service ID。"""
        return tuple(sorted(self._by_service))

    @property
    def index_stats(self) -> dict[str, int | bool]:
        """返回索引规模，供耗时日志和测试检查。"""
        return {
            "message_count": len(self._messages),
            "message_index_count": len(self._by_index),
            "service_key_count": len(self._by_service),
            "method_key_count": len(self._by_method),
            "sd_entry_type_count": len(self._by_sd_entry_type),
            "time_ordered": self._time_ordered,
        }

    @property
    def notification_evidence(self) -> dict[tuple[int, int], tuple[dict[str, Any], ...]]:
        """按 ``(Service ID, Method/Event ID)`` 返回 Notification 证据索引。"""
        return {
            key: tuple(build_message_evidence(message, kind="Notification") for message in values)
            for key, values in self._notifications.items()
        }

    def get(self, message_index: int) -> dict[str, Any] | None:
        """按逻辑消息索引 O(1) 读取完整消息。"""
        return self._by_index.get(message_index)

    def for_service(self, service_id: int) -> tuple[dict[str, Any], ...]:
        """读取普通 Header 或 SD Entry 中涉及指定服务的消息。"""
        return self._by_service.get(service_id, ())

    def first_for_service(self, service_id: int) -> dict[str, Any] | None:
        """读取指定服务在抓包中的首次出现消息。"""
        messages = self.for_service(service_id)
        return messages[0] if messages else None

    def notifications_for_service(self, service_id: int) -> tuple[dict[str, Any], ...]:
        """读取指定服务的全部 Notification，不包含 SD 报文。"""
        return self._notifications_by_service.get(service_id, ())

    @property
    def all_notifications(self) -> tuple[dict[str, Any], ...]:
        """返回全部非 SD Notification，供信号元数据页面复用。"""
        return self._all_notifications

    def notification_messages(
        self,
        service_id: int,
        method_ids: set[int] | None = None,
        *,
        parse_status: str | None = None,
        require_parsed: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        """查询信号时序和订阅诊断共用的 Notification 候选消息。"""
        result = []
        for message in self.notifications_for_service(service_id):
            if method_ids is not None and header_int(message, "method_id") not in method_ids:
                continue
            if parse_status and str(message.get("parse_status", "")).casefold() != parse_status.casefold():
                continue
            if require_parsed and not message.get("parsed"):
                continue
            result.append(message)
        return tuple(result)

    def search(
        self,
        *,
        service_id: int | None = None,
        method_id: int | None = None,
        message_type: str = "",
        src_ip: str | None = None,
        dst_ip: str | None = None,
        sd_entry_type: str = "",
        parse_status: str = "",
        start_time: float | None = None,
        end_time: float | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> MessageSearchResult:
        """组合索引过滤消息，只保留当前分页引用并统计完整匹配数量。"""
        type_query = message_type.strip().casefold()
        entry_query = sd_entry_type.strip().casefold()
        status_query = parse_status.strip().casefold()
        candidates: list[tuple[dict[str, Any], ...]] = []
        if service_id is not None:
            candidates.append(self._by_service.get(service_id, ()))
        if method_id is not None:
            candidates.append(self._by_method.get(method_id, ()))
        if src_ip:
            candidates.append(self._by_src_ip.get(src_ip, ()))
        if dst_ip:
            candidates.append(self._by_dst_ip.get(dst_ip, ()))
        if status_query:
            candidates.append(self._by_parse_status.get(status_query, ()))

        numeric_type = _parse_type_query(type_query)
        if numeric_type is not None:
            candidates.append(self._by_message_type.get(numeric_type, ()))
        elif type_query in self._by_kind:
            candidates.append(self._by_kind[type_query])
        if entry_query in self._by_sd_entry_type:
            candidates.append(self._by_sd_entry_type[entry_query])

        time_candidates = self._time_slice(start_time, end_time)
        if time_candidates is not None:
            candidates.append(time_candidates)
        source = min(candidates, key=len) if candidates else self._messages

        matched_count = 0
        page: list[dict[str, Any]] = []
        for message in source:
            if service_id is not None and service_id not in message_service_ids(message):
                continue
            if method_id is not None and header_int(message, "method_id") != method_id:
                continue
            if src_ip and message.get("src_ip") != src_ip:
                continue
            if dst_ip and message.get("dst_ip") != dst_ip:
                continue
            if status_query and str(message.get("parse_status", "unresolved")).casefold() != status_query:
                continue
            if type_query and not _matches_message_type(message, type_query):
                continue
            if entry_query and not _matches_sd_entry(message, entry_query):
                continue
            if not in_time_range(message, start_time, end_time):
                continue
            if offset <= matched_count < offset + limit:
                page.append(message)
            matched_count += 1

        next_offset = offset + len(page) if offset + len(page) < matched_count else None
        return MessageSearchResult(matched_count, tuple(page), offset, next_offset)

    def _time_slice(
        self,
        start_time: float | None,
        end_time: float | None,
    ) -> tuple[dict[str, Any], ...] | None:
        """时间戳单调时使用二分切片；非单调抓包返回 None 触发安全回退。"""
        if not self._time_ordered or (start_time is None and end_time is None):
            return None
        left = bisect_left(self._timestamps, start_time) if start_time is not None else 0
        right = bisect_right(self._timestamps, end_time) if end_time is not None else len(self._messages)
        return self._messages[left:right]


def _freeze_index(index: dict[Any, list[dict[str, Any]]]) -> dict[Any, tuple[dict[str, Any], ...]]:
    """把构建阶段的可变列表冻结为只读使用约定的元组。"""
    return {key: tuple(values) for key, values in index.items()}


def _parse_type_query(query: str) -> int | None:
    if not query:
        return None
    try:
        value = int(query, 0)
    except ValueError:
        return None
    return value if 0 <= value <= 0xFF else None


def _matches_message_type(message: dict[str, Any], query: str) -> bool:
    value = header_int(message, "message_type")
    candidates = {
        str(value).casefold(),
        f"0x{value:02x}",
        message_type_label(value).casefold(),
        str(message.get("message_kind", "")).casefold(),
    }
    return any(query == candidate or query in candidate for candidate in candidates)


def _matches_sd_entry(message: dict[str, Any], query: str) -> bool:
    return any(
        query in str(entry.get("type", "")).casefold()
        for entry in message.get("sd", {}).get("entries", [])
    )


__all__ = ["MessageQuery", "MessageSearchResult"]
