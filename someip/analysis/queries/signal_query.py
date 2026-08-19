"""Notification 与反序列化信号字段的统一查询。"""
from __future__ import annotations

from collections import Counter
from statistics import median
from typing import Any

from someip.analysis.signal_utils import (
    collect_leaf_paths,
    detect_transitions,
    find_field_node,
    get_field_value,
)

from .evidence import build_message_evidence, format_hex, header_int, in_time_range
from .message_query import MessageQuery


class SignalQuery:
    """复用 Notification 索引，提供 Web 曲线和 AI 统计所需的同源数据。"""

    def __init__(self, messages: MessageQuery, registry: Any = None):
        self._messages = messages
        self._registry = registry
        self._meta_cache: tuple[dict[str, Any], ...] | None = None

    def metadata(self) -> list[dict[str, Any]]:
        """返回服务、事件和字段路径层级；首次读取后复用缓存。"""
        if self._meta_cache is None:
            self._meta_cache = self._build_metadata()
        # Web 层会把 events 字典替换为列表，因此返回浅层副本隔离展示修改。
        return [
            {**service, "events": [dict(event) for event in service["events"]]}
            for service in self._meta_cache
        ]

    def field_series(
        self,
        service_id: int,
        event_id: int,
        field_paths: list[str],
        *,
        start_time: float | None = None,
        end_time: float | None = None,
    ) -> dict[str, Any]:
        """提取一个事件的多个数值字段，供曲线和字段统计共同使用。"""
        candidates = self._notification_candidates(service_id, event_id)
        candidates = [
            message
            for message in candidates
            if in_time_range(message, start_time, end_time)
        ]
        candidates.sort(key=lambda message: (
            float(message.get("timestamp_epoch") or 0.0),
            int(message.get("frame_index") or 0),
        ))

        fields: list[dict[str, Any]] = []
        for field_path in field_paths:
            parts = [part for part in field_path.split(".") if part]
            points: list[dict[str, Any]] = []
            for seq, message in enumerate(candidates, 1):
                value = get_field_value(message.get("parsed") or {}, parts)
                if value is None:
                    continue
                points.append({
                    "seq": seq,
                    "message_index": int(message.get("index", -1)),
                    "frame_index": int(message.get("frame_index", 0)),
                    "timestamp_epoch": float(message.get("timestamp_epoch") or 0.0),
                    "timestamp_iso": message.get("timestamp_iso", ""),
                    "value": value,
                })
            fields.append({
                "field_path": field_path,
                "points": points,
                "transitions": detect_transitions(points),
            })
        return {"service_id": service_id, "event_id": event_id, "fields": fields}

    def notification_statistics(
        self,
        *,
        service_id: int | None = None,
        method_id: int | None = None,
        field_path: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
    ) -> dict[str, Any]:
        """统计 Notification 数量、时间间隔、端点和可选的数值字段。"""
        if service_id is None:
            candidates = self._messages.all_notifications
        elif method_id is None:
            candidates = self._messages.notifications_for_service(service_id)
        else:
            candidates = self._notification_candidates(
                service_id,
                method_id,
                parsed_only=False,
            )

        filtered = [
            message
            for message in candidates
            if in_time_range(message, start_time, end_time)
        ]
        groups: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for message in filtered:
            key = (header_int(message, "service_id"), header_int(message, "method_id"))
            groups.setdefault(key, []).append(message)

        rows = [
            self._notification_group(sid, mid, messages, field_path)
            for (sid, mid), messages in sorted(groups.items())
        ]
        return {
            "filters": {
                "service_id": format_hex(service_id) if service_id is not None else None,
                "method_id": format_hex(method_id) if method_id is not None else None,
                "field_path": field_path,
                "start_time": start_time,
                "end_time": end_time,
            },
            "notification_count": len(filtered),
            "event_count": len(rows),
            "events": rows,
        }

    def payload_field(self, message_index: int, field_path: str) -> dict[str, Any]:
        """按路径读取单个 Payload 节点，避免返回完整深层解析树。"""
        message = self._messages.get(message_index)
        if message is None:
            raise ValueError(f"消息索引 {message_index} 不存在")
        parsed = message.get("parsed")
        if not isinstance(parsed, dict):
            raise ValueError(f"消息索引 {message_index} 没有可查询的反序列化树")

        normalized = field_path.strip().strip(".")
        if not normalized:
            raise ValueError("field_path 不能为空")
        node = find_field_node(parsed, normalized.split("."))
        if node is None:
            paths = collect_leaf_paths(parsed)
            raise ValueError(
                f"字段路径 {normalized} 不存在；可用路径示例: {paths[:20]}"
            )

        # 容器节点只返回直接子字段名，防止一次查询再次展开整棵深层子树。
        children = node.get("children", []) if isinstance(node.get("children"), list) else []
        field = {
            key: node.get(key)
            for key in ("name", "type", "kind", "offset", "byte_size")
            if key in node
        }
        if "value" in node:
            field["value"], field["value_truncated"] = _bounded_scalar(
                node.get("value"), 4_096
            )
        if "hex" in node:
            field["hex"], field["hex_truncated"] = _bounded_scalar(
                node.get("hex"), 8_192
            )
        return {
            "evidence": build_message_evidence(message),
            "service_id": format_hex(header_int(message, "service_id")),
            "method_id": format_hex(header_int(message, "method_id")),
            "field_path": normalized,
            "field": field,
            "child_names": [str(child.get("name", "")) for child in children[:100]],
            "children_truncated": len(children) > 100,
        }

    def _build_metadata(self) -> tuple[dict[str, Any], ...]:
        services: dict[int, dict[str, Any]] = {}
        for message in self._messages.all_notifications:
            if message.get("parse_status") != "ok" or not message.get("parsed"):
                continue
            service_id = header_int(message, "service_id")
            method_id = header_int(message, "method_id")
            service = services.setdefault(service_id, {
                "service_id": service_id,
                "service_id_hex": format_hex(service_id),
                "service_name": self._service_name(service_id) or "",
                "events": {},
            })
            if method_id not in service["events"]:
                fields = collect_leaf_paths(message["parsed"])
                if fields:
                    service["events"][method_id] = {
                        "event_id": method_id,
                        "event_id_hex": format_hex(method_id),
                        "event_name": self._event_name(service_id, method_id) or "",
                        "fields": fields,
                    }

        result = []
        for service_id in sorted(services):
            service = services[service_id]
            result.append({
                **service,
                "events": tuple(
                    service["events"][event_id]
                    for event_id in sorted(service["events"])
                ),
            })
        return tuple(result)

    def _notification_candidates(
        self,
        service_id: int,
        event_id: int,
        *,
        parsed_only: bool = True,
    ) -> tuple[dict[str, Any], ...]:
        """兼容 Event ID 是否携带 0x8000 高位的两种输入。"""
        method_ids = {event_id, event_id ^ 0x8000}
        return self._messages.notification_messages(
            service_id,
            method_ids,
            parse_status="ok" if parsed_only else None,
            require_parsed=parsed_only,
        )

    def _notification_group(
        self,
        service_id: int,
        method_id: int,
        messages: list[dict[str, Any]],
        field_path: str | None,
    ) -> dict[str, Any]:
        ordered = sorted(messages, key=lambda message: (
            float(message.get("timestamp_epoch") or 0.0),
            int(message.get("frame_index") or 0),
        ))
        timestamps = [float(message.get("timestamp_epoch") or 0.0) for message in ordered]
        intervals = [later - earlier for earlier, later in zip(timestamps, timestamps[1:])]
        evidences = [build_message_evidence(message, kind="Notification") for message in ordered]
        result: dict[str, Any] = {
            "service_id": format_hex(service_id),
            "service_name": self._service_name(service_id),
            "method_id": format_hex(method_id),
            "event_name": self._event_name(service_id, method_id),
            "notification_count": len(ordered),
            "parsed_count": sum(bool(message.get("parsed")) for message in ordered),
            "parse_status_counts": dict(Counter(
                str(message.get("parse_status", "unresolved")) for message in ordered
            )),
            "source_ips": dict(Counter(str(message.get("src_ip") or "") for message in ordered)),
            "destination_ips": dict(Counter(str(message.get("dst_ip") or "") for message in ordered)),
            "first_evidence": evidences[0],
            "last_evidence": evidences[-1],
            "evidence_samples": _sample_evidence(evidences, 4),
            "interval_seconds": {
                "sample_count": len(intervals),
                "minimum": min(intervals) if intervals else None,
                "maximum": max(intervals) if intervals else None,
                "average": sum(intervals) / len(intervals) if intervals else None,
                "median": median(intervals) if intervals else None,
            },
        }
        if field_path:
            parts = [part for part in field_path.split(".") if part]
            points = []
            for seq, message in enumerate(ordered, 1):
                value = get_field_value(message.get("parsed") or {}, parts)
                if value is None:
                    continue
                points.append({
                    "seq": seq,
                    "frame_index": int(message.get("frame_index", 0)),
                    "timestamp_epoch": float(message.get("timestamp_epoch") or 0.0),
                    "timestamp_iso": message.get("timestamp_iso", ""),
                    "value": value,
                })
            values = [point["value"] for point in points]
            result["field_statistics"] = {
                "field_path": field_path,
                "value_count": len(values),
                "missing_count": len(ordered) - len(values),
                "minimum": min(values) if values else None,
                "maximum": max(values) if values else None,
                "average": sum(values) / len(values) if values else None,
                "first_value": values[0] if values else None,
                "last_value": values[-1] if values else None,
                "transition_count": len(detect_transitions(points)),
            }
        return result

    def _service_name(self, service_id: int) -> str | None:
        try:
            return self._registry.lookup_service_name(service_id) if self._registry else None
        except Exception:
            return None

    def _event_name(self, service_id: int, method_id: int) -> str | None:
        if not self._registry:
            return None
        try:
            for candidate in (method_id & 0x7FFF, method_id):
                name = self._registry.lookup_event_name(service_id, candidate)
                if name:
                    return name
        except Exception:
            return None
        return None


def _sample_evidence(
    evidences: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """等量保留首尾证据，既限制上下文又覆盖完整时间范围。"""
    if len(evidences) <= limit:
        return evidences
    head = limit // 2
    return evidences[:head] + evidences[-(limit - head):]


def _bounded_scalar(value: Any, maximum_chars: int) -> tuple[Any, bool]:
    """限制字符串字段大小；数字和布尔值保持原类型。"""
    if not isinstance(value, str):
        return value, False
    return value[:maximum_chars], len(value) > maximum_chars


__all__ = ["SignalQuery"]
