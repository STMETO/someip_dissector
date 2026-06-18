"""
解析结果节点 — 反序列化产出的"一砖一瓦"。

纯数据容器，不包含解析逻辑。每个节点代表二进制 payload 中的
一个字段（基础类型 / 结构体 / 数组元素），通过 children 串联成树。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FieldNode:
    """解析树中的一个节点。

    Attributes
    ----------
    name:
        字段名，根节点为消息类型路径。
    type_name:
        类型名称（如 ``"UINT16"``、``"Struct_DiagnosticRequest"``）。
    value:
        解析后的值。基础类型为 int / str / bool；
        复合类型为 None（值在 children 中）。
    offset:
        该字段在 payload 中的起始字节偏移。
    byte_size:
        该字段自身占用的字节数（不含子节点）。
    hex:
        原始字节的十六进制字符串（用于调试和前端展示）。
    children:
        子节点列表。结构体字段 → 子 FieldNode，数组元素 → 多个 FieldNode。
    """

    name: str
    type_name: str
    value: Any = None
    offset: int = 0
    byte_size: int = 0
    hex: str = ""
    children: list[FieldNode] = field(default_factory=list)

    # ------------------------------------------------------------------
    # 工厂方法
    # ------------------------------------------------------------------

    @classmethod
    def leaf(
        cls,
        name: str,
        type_name: str,
        value: Any,
        offset: int,
        raw: bytes,
    ) -> FieldNode:
        """创建叶节点（基础类型）。"""
        return cls(
            name=name,
            type_name=type_name,
            value=value,
            offset=offset,
            byte_size=len(raw),
            hex=raw.hex(),
        )

    @classmethod
    def container(
        cls,
        name: str,
        type_name: str,
        offset: int,
        byte_size: int,
        children: list[FieldNode],
    ) -> FieldNode:
        """创建容器节点（结构体 / 数组）。"""
        return cls(
            name=name,
            type_name=type_name,
            value=None,
            offset=offset,
            byte_size=byte_size,
            hex="",
            children=children,
        )

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """递归转为可 JSON 序列化的字典。"""
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
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d
