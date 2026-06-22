"""
解析结果节点 — 反序列化
纯数据容器，不包含任何二进制解析逻辑。
通过 children 父子关联，组成完整树形报文结构，用于前端展示、JSON 导出。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FieldNode:
    """二进制报文解析树通用节点。

    节点分类（由工厂方法保证）：
        leaf      — 基础类型 uint8/int32/字符串，有 value，无 children
        container — 结构体/数组/SD/未解析，无 value，有 children
    """

    name: str
    type_name: str
    value: Any = None
    offset: int = 0
    byte_size: int = 0
    hex: str = ""
    children: list[FieldNode] = field(default_factory=list)

    _is_container: bool = field(default=False, repr=False)
    # 可选元标记："" | "sd" | "unresolved" — 前端据此显示状态徽标
    _meta_kind: str = field(default="", repr=False)

    # ------------------------------------------------------------------
    # 工厂方法
    # ------------------------------------------------------------------

    @classmethod
    def leaf(cls, *, name: str, type_name: str, value: Any,
             offset: int, raw: bytes) -> FieldNode:
        """叶子节点：基础类型 / 字符串单一数值。"""
        return cls(name=name, type_name=type_name, value=value,
                   offset=offset, byte_size=len(raw), hex=raw.hex())

    @classmethod
    def container(cls, *, name: str, type_name: str, offset: int,
                  byte_size: int, children: list[FieldNode],
                  meta_kind: str = "") -> FieldNode:
        """容器节点：结构体 / 数组 / SD / 未解析报文。"""
        return cls(name=name, type_name=type_name, value=None,
                   offset=offset, byte_size=byte_size, hex="",
                   children=children, _is_container=True,
                   _meta_kind=meta_kind)

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """递归转换为字典。"""
        d: dict[str, Any] = {
            "name": self.name,
            "type": self.type_name,
            "offset": self.offset,
            "byte_size": self.byte_size,
        }
        if self.hex:
            d["hex"] = self.hex
        if self.value is not None:
            d["value"] = self.value
        if self._meta_kind:
            d["meta_kind"] = self._meta_kind

        if self._is_container:
            d["kind"] = "container"
            d["children"] = [c.to_dict() for c in self.children]
        else:
            d["kind"] = "leaf"
        return d
