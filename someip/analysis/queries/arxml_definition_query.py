"""ARXML 服务、成员和字段定义查询。"""
from __future__ import annotations

import re
from typing import Any

from someip.datatypes.types import ArrayType, BaseType, StringType, StructureType

from .evidence import format_hex

_MEMBER_KINDS = {"all", "method", "event", "eventgroup"}


class ArxmlDefinitionQuery:
    """通过 ServiceRegistry 的公开快照查询 ARXML，不暴露整份源文件。"""

    def __init__(self, registry: Any = None, type_pool: dict[str, Any] | None = None):
        self._registry = registry
        self._type_pool = type_pool or {}

    def query(
        self,
        service_id: int,
        *,
        member_kind: str = "all",
        member_id: int | None = None,
        field_path: str | None = None,
    ) -> dict[str, Any]:
        """返回一个服务的有限定义，可继续按成员 ID 和字段路径收窄。"""
        kind = member_kind.strip().casefold() or "all"
        if kind not in _MEMBER_KINDS:
            raise ValueError("member_kind 必须是 all、method、event 或 eventgroup")
        definition = self._describe_service(service_id)
        if definition is None:
            return {
                "service_id": format_hex(service_id),
                "found": False,
                "available_services": self._available_services(),
            }

        result: dict[str, Any] = {
            "service_id": format_hex(service_id),
            "service_name": definition.get("service_name"),
            "interface_ref": definition.get("interface_ref"),
            "found": True,
        }
        methods = []
        if kind in {"all", "method"}:
            for method in definition.get("methods", []):
                if member_id is not None and int(method.get("method_id", -1)) != member_id:
                    continue
                methods.append({
                    "method_id": format_hex(int(method.get("method_id", 0))),
                    "name": method.get("name"),
                    "method_ref": method.get("method_ref"),
                    "arguments": [
                        self._argument_definition(argument, field_path)
                        for argument in method.get("arguments", [])
                    ],
                })
        events = []
        if kind in {"all", "event"}:
            for event in definition.get("events", []):
                event_id = int(event.get("event_id", -1))
                # 抓包中的 Event ID 可能带 0x8000 标志，ARXML 部署常保存低 15 位。
                if member_id is not None and event_id not in {member_id, member_id & 0x7FFF}:
                    continue
                events.append({
                    "event_id": format_hex(event_id),
                    "name": event.get("name"),
                    "event_ref": event.get("event_ref"),
                    "type_ref": event.get("type_ref"),
                    "type_definition": self._type_definition(
                        event.get("type_ref", ""), field_path
                    ),
                })
        eventgroups = []
        if kind in {"all", "eventgroup"}:
            for eventgroup in definition.get("eventgroups", []):
                if member_id is not None and int(eventgroup.get("eventgroup_id", -1)) != member_id:
                    continue
                eventgroups.append({
                    "eventgroup_id": format_hex(int(eventgroup.get("eventgroup_id", 0))),
                    "name": eventgroup.get("name"),
                })

        result.update({
            "member_filter": {
                "kind": kind,
                "member_id": format_hex(member_id) if member_id is not None else None,
                "field_path": field_path,
            },
            "methods": methods,
            "events": events,
            "eventgroups": eventgroups,
            "matched_member_count": len(methods) + len(events) + len(eventgroups),
        })
        return result

    def _describe_service(self, service_id: int) -> dict[str, Any] | None:
        try:
            if self._registry and hasattr(self._registry, "describe_service"):
                return self._registry.describe_service(service_id)
        except Exception:
            return None
        return None

    def _available_services(self) -> list[dict[str, Any]]:
        try:
            services = self._registry.list_services() if self._registry else []
        except Exception:
            services = []
        return [
            {"service_id": format_hex(int(service_id)), "service_name": name}
            for service_id, name in services[:50]
        ]

    def _argument_definition(
        self,
        argument: dict[str, Any],
        field_path: str | None,
    ) -> dict[str, Any]:
        type_ref = str(argument.get("type_ref") or "")
        return {
            "name": argument.get("name"),
            "direction": argument.get("direction"),
            "type_ref": type_ref,
            "type_definition": self._type_definition(type_ref, field_path),
        }

    def _type_definition(
        self,
        type_ref: str,
        field_path: str | None,
    ) -> dict[str, Any] | None:
        data_type = _resolve_type(self._type_pool, type_ref)
        if data_type is None:
            return None
        if field_path:
            parts = [part for part in field_path.split(".") if part]
            matched = _find_field(data_type, parts)
            if matched is None:
                return {"field_path": field_path, "found": False}
            field_name, field_type, static_offset = matched
            return {
                "field_path": field_path,
                "found": True,
                "field_name": field_name,
                "static_offset": static_offset,
                "offset_reliable": static_offset is not None,
                "definition": _describe_type(field_type, depth=3, seen=set()),
            }
        return _describe_type(data_type, depth=3, seen=set())


def _resolve_type(type_pool: dict[str, Any], type_ref: str) -> Any | None:
    if not type_ref:
        return None
    direct = type_pool.get(type_ref)
    if direct is not None:
        return direct
    normalized = type_ref.rstrip("/")
    candidates = [
        data_type for path, data_type in type_pool.items()
        if path.rstrip("/") == normalized or path.rstrip("/").endswith(normalized)
    ]
    return candidates[0] if len(candidates) == 1 else None


def _describe_type(data_type: Any, *, depth: int, seen: set[int]) -> dict[str, Any]:
    """生成有深度上限的类型描述，阻止递归类型撑大 Tool 结果。"""
    base = {
        "name": getattr(data_type, "name", type(data_type).__name__),
        "path": getattr(data_type, "path", ""),
        "kind": type(data_type).__name__,
        "byte_size": int(getattr(data_type, "byte_size", 0) or 0),
        "byte_size_reliable": True,
    }
    identity = id(data_type)
    if depth <= 0 or identity in seen:
        base["truncated"] = True
        return base
    next_seen = set(seen)
    next_seen.add(identity)

    if isinstance(data_type, BaseType):
        base.update({
            "bit_length": data_type.bit_length,
            "byte_order": data_type.byte_order,
            "signed": data_type.is_signed,
            "floating_point": data_type.is_float,
        })
    elif isinstance(data_type, StringType):
        base["dynamic_length"] = True
        base["byte_size"] = None
        base["byte_size_reliable"] = False
    elif isinstance(data_type, StructureType):
        size_reliable = all(
            field.resolved_type is not None and field.resolved_type.byte_size > 0
            for field in data_type.fields
        )
        if not size_reliable:
            base["byte_size"] = None
            base["byte_size_reliable"] = False
        base["fields"] = _describe_structure_fields(
            data_type,
            depth=depth,
            seen=next_seen,
        )
        base["fields_truncated"] = len(data_type.fields) > 80
    elif isinstance(data_type, ArrayType):
        size_reliable = (
            not data_type.is_dynamic
            and data_type.element_type is not None
            and data_type.element_type.byte_size > 0
        )
        if not size_reliable:
            base["byte_size"] = None
            base["byte_size_reliable"] = False
        base.update({
            "length": data_type.length,
            "dynamic_length": data_type.is_dynamic,
            "element_type_ref": data_type.element_type_ref,
            "element_definition": (
                _describe_type(data_type.element_type, depth=depth - 1, seen=next_seen)
                if data_type.element_type is not None else None
            ),
        })
    return base


def _find_field(
    data_type: Any,
    parts: list[str],
    offset: int | None = 0,
) -> tuple[str, Any, int | None] | None:
    if not parts:
        return getattr(data_type, "name", ""), data_type, offset
    if parts and parts[0] == getattr(data_type, "name", None):
        parts = parts[1:]
        if not parts:
            return getattr(data_type, "name", ""), data_type, offset
    if isinstance(data_type, ArrayType):
        if data_type.element_type is None:
            return None
        return _find_field(data_type.element_type, parts, offset)
    if not isinstance(data_type, StructureType):
        return None
    target, array_index = _path_segment(parts[0])
    running_offset = offset
    for field in data_type.fields:
        resolved_field = field.resolved_type
        if field.name != target or resolved_field is None:
            if running_offset is not None:
                field_size = int(getattr(resolved_field, "byte_size", 0) or 0)
                running_offset = running_offset + field_size if field_size > 0 else None
            continue
        field_offset = running_offset
        resolved = resolved_field
        if array_index is not None:
            if not isinstance(resolved, ArrayType) or resolved.element_type is None:
                return None
            if resolved.is_dynamic or resolved.element_type.byte_size <= 0:
                field_offset = None
            elif field_offset is not None:
                field_offset += array_index * resolved.element_type.byte_size
            resolved = resolved.element_type
        if len(parts) == 1:
            return parts[0], resolved, field_offset
        return _find_field(resolved, parts[1:], field_offset)
    return None


def _describe_structure_fields(
    data_type: StructureType,
    *,
    depth: int,
    seen: set[int],
) -> list[dict[str, Any]]:
    """标出静态偏移是否可靠；变长字段之后的偏移只能在运行时确定。"""
    rows = []
    running_offset: int | None = 0
    for field in data_type.fields[:80]:
        resolved = field.resolved_type
        rows.append({
            "name": field.name,
            "type_ref": field.type_ref,
            "static_offset": running_offset,
            "offset_reliable": running_offset is not None,
            "definition": (
                _describe_type(resolved, depth=depth - 1, seen=seen)
                if resolved is not None else None
            ),
        })
        if running_offset is not None:
            field_size = int(getattr(resolved, "byte_size", 0) or 0)
            running_offset = running_offset + field_size if field_size > 0 else None
    return rows


def _path_segment(value: str) -> tuple[str, int | None]:
    match = re.fullmatch(r"([^\[]+)(?:\[(\d+)\])?", value.strip())
    if not match:
        return value.strip(), None
    return match.group(1), int(match.group(2)) if match.group(2) is not None else None


__all__ = ["ArxmlDefinitionQuery"]
