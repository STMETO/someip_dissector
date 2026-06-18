"""
DataType 类型体系 — 反序列化的可执行数据类型对象。

从 ARXML 编译而来，每个对象已内置字段布局、偏移、字节序、长度，
反序列化时可直接计算，不再依赖 XML。
"""

from __future__ import annotations

import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass

FieldNode = None  # type: ignore  # 占位，实际通过 _import_field_node() 延迟加载


def _import_field_node():
    """延迟导入 FieldNode，避免 arxml_parsers ↔ deserialization 循环依赖。"""
    from deserialization.field_node import FieldNode
    return FieldNode


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

    @abstractmethod
    def deserialize(self, payload: bytes, offset: int, name: str) -> "FieldNode":
        """从 payload[offset:] 反序列化一个字段节点。

        Parameters
        ----------
        payload: 完整二进制负载。
        offset: 当前字段的起始字节偏移。
        name: 该字段的名称（用于 FieldNode.name）。

        Returns
        -------
        FieldNode
            包含解析值、子节点、字节偏移和原始十六进制的节点。
        """
        ...

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r} size={self.byte_size}>"


# ── 基础类型 ──────────────────────────────────────────────


class BaseType(DataType):
    """基础类型（uint8, int32, float, boolean...）。"""

    def __init__(
        self,
        name: str,
        path: str = "",
        *,
        bit_length: int = 8,
        byte_order: str = "big",
        is_signed: bool = False,
        is_float: bool = False,
    ) -> None:
        super().__init__(name, path)
        self.bit_length = bit_length
        self.byte_order = byte_order
        self.is_signed = is_signed
        self.is_float = is_float

    @property
    def byte_size(self) -> int:
        return self.bit_length // 8

    _STRUCT_FMT: dict[tuple[int, bool, str], str] = {
        (8, False, "big"): ">B",   (8, False, "little"): "<B",
        (16, False, "big"): ">H",  (16, False, "little"): "<H",
        (32, False, "big"): ">I",  (32, False, "little"): "<I",
        (64, False, "big"): ">Q",  (64, False, "little"): "<Q",
        (8, True, "big"): ">b",    (8, True, "little"): "<b",
        (16, True, "big"): ">h",   (16, True, "little"): "<h",
        (32, True, "big"): ">i",   (32, True, "little"): "<i",
        (64, True, "big"): ">q",   (64, True, "little"): "<q",
    }

    def _struct_fmt(self) -> str:
        if self.is_float:
            if self.bit_length == 32:
                return ">f" if self.byte_order == "big" else "<f"
            if self.bit_length == 64:
                return ">d" if self.byte_order == "big" else "<d"
        return self._STRUCT_FMT.get(
            (self.bit_length, self.is_signed, self.byte_order), ">B"
        )

    def deserialize(self, payload: bytes, offset: int, name: str) -> FieldNode:
        size = self.byte_size
        raw = payload[offset:offset + size]
        fmt = self._struct_fmt()
        value = struct.unpack(fmt, raw)[0]
        return _import_field_node().leaf(name=name, type_name=self.name,
                                         value=value, offset=offset, raw=raw)

    def __repr__(self) -> str:
        if self.is_float:
            return f"<{type(self).__name__} f{self.bit_length} {self.name!r}>"
        sign = "i" if self.is_signed else "u"
        order = "le" if self.byte_order == "little" else ""
        return f"<{type(self).__name__} {sign}{self.bit_length}{order} {self.name!r}>"


# ── 变长类型 ──────────────────────────────────────────────


class StringType(DataType):
    """变长字符串 — 字节数由运行时数据决定。"""

    def __init__(self, name: str, path: str = "") -> None:
        super().__init__(name, path)

    def deserialize(self, payload: bytes, offset: int, name: str) -> FieldNode:
        """SOME/IP 字符串：4 字节 BE 长度前缀 + UTF-8 数据。"""
        if offset + 4 > len(payload):
            return _import_field_node().leaf(name=name, type_name=self.name,
                                  value="<truncated>", offset=offset, raw=b"")
        length = struct.unpack(">I", payload[offset:offset + 4])[0]
        raw = payload[offset:offset + 4 + length]
        try:
            value = payload[offset + 4:offset + 4 + length].decode("utf-8")
        except UnicodeDecodeError:
            value = raw[:32].hex() + ("..." if len(raw) > 32 else "")
        return _import_field_node().leaf(name=name, type_name=self.name,
                              value=value, offset=offset, raw=raw)

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

    def deserialize(self, payload: bytes, offset: int, name: str) -> FieldNode:
        total = self.byte_size  # 属性内部已调用 resolve_offsets()
        available = max(0, len(payload) - offset)
        if total > available:
            total = available
        children: list[FieldNode] = []
        for f in self.fields:
            if f.resolved_type is not None:
                children.append(
                    f.resolved_type.deserialize(payload, offset + f.offset, f.name)
                )
        return _import_field_node().container(name=name, type_name=self.name,
                                   offset=offset, byte_size=total,
                                   children=children)

    @property
    def byte_size(self) -> int:
        if not self.fields:
            return 0
        self.resolve_offsets()
        last = self.fields[-1]
        return last.offset + last.byte_size


# ── 数组 ──────────────────────────────────────────────────


class ArrayType(DataType):
    """数组 / 向量类型。

    Attributes
    ----------
    is_dynamic:
        True 表示 VECTOR（SOME/IP 动态长度，头部 4 字节 BE 计数）；
        False 表示 ARRAY（定长）。
    """

    def __init__(
        self,
        name: str,
        path: str = "",
        *,
        element_type_ref: str = "",
        element_type: DataType | None = None,
        length: int = 0,
        is_dynamic: bool = False,
    ) -> None:
        super().__init__(name, path)
        self.element_type_ref = element_type_ref
        self.element_type = element_type
        self.length = length
        self.is_dynamic = is_dynamic

    def deserialize(self, payload: bytes, offset: int, name: str) -> FieldNode:
        children: list[FieldNode] = []
        pos = offset

        if self.is_dynamic:
            # VECTOR: 先读 4 字节 BE 长度
            if pos + 4 > len(payload):
                return _import_field_node().container(name=name, type_name=self.name,
                                           offset=offset, byte_size=0, children=[])
            actual_len = struct.unpack(">I", payload[pos:pos + 4])[0]
            pos += 4
        else:
            actual_len = self.length

        if self.element_type is not None:
            for i in range(actual_len):
                if pos >= len(payload):
                    break
                child = self.element_type.deserialize(
                    payload, pos, f"{name}[{i}]"
                )
                children.append(child)
                pos += child.byte_size

        return _import_field_node().container(name=name, type_name=self.name,
                                   offset=offset, byte_size=pos - offset,
                                   children=children)

    @property
    def byte_size(self) -> int:
        if self.element_type is not None:
            return self.element_type.byte_size * self.length
        return 0
