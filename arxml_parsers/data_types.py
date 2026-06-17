"""
DataType 类型体系 — 反序列化的可执行数据类型对象。

从 ARXML 编译而来，每个对象已内置字段布局、偏移、字节序、长度，
反序列化时可直接计算，不再依赖 XML。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class DataType(ABC):
    """反序列化数据类型的抽象基类，统一所有类型接口。"""

    def __init__(self, name: str, path: str = "") -> None:
        self.name = name
        self.path = path  # ARXML 全局唯一路径

    @property
    @abstractmethod
    def byte_size(self) -> int:
        """类型占用的静态字节数（变长类型返回 0）。"""
        ...

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r} size={self.byte_size}>"


# ── 基础类型 ──────────────────────────────────────────────


class BaseType(DataType):
    """基础类型（uint8, int32, boolean...）。"""

    def __init__(
        self,
        name: str,
        path: str = "",
        *,
        bit_length: int = 8,
        byte_order: str = "big",
        is_signed: bool = False,
    ) -> None:
        super().__init__(name, path)
        self.bit_length = bit_length
        self.byte_order = byte_order
        self.is_signed = is_signed

    @property
    def byte_size(self) -> int:
        return self.bit_length // 8

    def __repr__(self) -> str:
        sign = "i" if self.is_signed else "u"
        order = "le" if self.byte_order == "little" else ""
        return f"<{type(self).__name__} {sign}{self.bit_length}{order} {self.name!r}>"


# ── 变长类型 ──────────────────────────────────────────────


class StringType(DataType):
    """变长字符串 — 字节数由运行时数据决定。"""

    def __init__(self, name: str, path: str = "") -> None:
        super().__init__(name, path)

    @property
    def byte_size(self) -> int:
        return 0  # 编译时不可知


# ── 结构体 ────────────────────────────────────────────────


@dataclass
class StructField:
    """结构体中的一个字段。"""

    name: str
    type_ref: str                           # 原始 ARXML 引用路径
    resolved_type: DataType | None = None   # 解析后的真实类型对象
    offset: int = 0                         # 字节偏移

    @property
    def byte_size(self) -> int:
        if self.resolved_type is not None:
            return self.resolved_type.byte_size
        return 0


class StructureType(DataType):
    """结构体：包含有序字段，自动计算偏移和总大小。"""

    def __init__(self, name: str, path: str = "") -> None:
        super().__init__(name, path)
        self.fields: list[StructField] = []

    def add_field(self, field: StructField) -> None:
        self.fields.append(field)

    def resolve_offsets(self) -> None:
        offset = 0
        for f in self.fields:
            f.offset = offset
            offset += f.byte_size

    @property
    def byte_size(self) -> int:
        if not self.fields:
            return 0
        self.resolve_offsets()
        last = self.fields[-1]
        return last.offset + last.byte_size


# ── 数组 ──────────────────────────────────────────────────


class ArrayType(DataType):
    """数组 / 向量类型。"""

    def __init__(
        self,
        name: str,
        path: str = "",
        *,
        element_type_ref: str = "",
        element_type: DataType | None = None,
        length: int = 0,
    ) -> None:
        super().__init__(name, path)
        self.element_type_ref = element_type_ref
        self.element_type = element_type
        self.length = length

    @property
    def byte_size(self) -> int:
        if self.element_type is not None:
            return self.element_type.byte_size * self.length
        return 0
