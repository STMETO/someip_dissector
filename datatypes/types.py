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
    """反序列化数据类型的抽象基类。"""

    def __init__(self, name: str, path: str = "") -> None:
        self.name = name
        self.path = path

    @property
    @abstractmethod
    def byte_size(self) -> int:
        """静态字节数（变长返回 0，仅用于编译期分析）。"""
        ...

    @abstractmethod
    def deserialize(self, payload: bytes, offset: int, name: str) -> tuple["FieldNode", int]:
        """从 payload[offset:] 反序列化。

        Returns
        -------
        (FieldNode, consumed_bytes)
            consumed_bytes 是实际消耗的字节数，用于流式推进位置。
        """
        ...

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r} size={self.byte_size}>"


# ══════════════════════════════════════════════════════════════
# BaseType — 定长基础类型
# ══════════════════════════════════════════════════════════════


class BaseType(DataType):
    """基础类型（uint8, int32, float, boolean...）。"""

    def __init__(
        self, name: str, path: str = "", *,
        bit_length: int = 8, byte_order: str = "big",
        is_signed: bool = False, is_float: bool = False,
    ) -> None:
        super().__init__(name, path)
        self.bit_length = bit_length
        self.byte_order = byte_order
        self.is_signed = is_signed
        self.is_float = is_float

    @property
    def byte_size(self) -> int:
        return self.bit_length // 8

    # _fmt () 格式化映射表
    _FMT: dict[tuple[int, bool, str], str] = {
        (8, False, "big"): ">B",  (8, False, "little"): "<B",
        (16, False, "big"): ">H", (16, False, "little"): "<H",
        (32, False, "big"): ">I", (32, False, "little"): "<I",
        (64, False, "big"): ">Q", (64, False, "little"): "<Q",
        (8, True, "big"): ">b",   (8, True, "little"): "<b",
        (16, True, "big"): ">h",  (16, True, "little"): "<h",
        (32, True, "big"): ">i",  (32, True, "little"): "<i",
        (64, True, "big"): ">q",  (64, True, "little"): "<q",
    }

    def _fmt(self) -> str:
        if self.is_float:
            return ">f" if (self.bit_length == 32 and self.byte_order == "big") else \
                   "<f" if (self.bit_length == 32) else \
                   ">d" if self.byte_order == "big" else "<d"
        return self._FMT.get((self.bit_length, self.is_signed, self.byte_order), ">B")

    def deserialize(self, payload: bytes, offset: int, name: str) -> tuple[FieldNode, int]:
        # 1. 获取当前基础类型固定字节长度
        size = self.byte_size
        # 2. 截取当前需要解析的一段二进制
        raw = payload[offset:offset + size]
        # 3. 根据大小端/符号类型解包，取第一个值
        value = struct.unpack(self._fmt(), raw)[0]
        # 4. 生成叶子节点（无孩子，单纯一个数值）
        node = _import_field_node().leaf(
            name=name, type_name=self.name, value=value, offset=offset, raw=raw)
        # 5. 返回节点 + 消耗字节数（固定size）
        return node, size


    def __repr__(self) -> str:
        if self.is_float:
            return f"<{type(self).__name__} f{self.bit_length} {self.name!r}>"
        sign = "i" if self.is_signed else "u"
        order = "le" if self.byte_order == "little" else ""
        return f"<{type(self).__name__} {sign}{self.bit_length}{order} {self.name!r}>"


# ══════════════════════════════════════════════════════════════
# BoolType — 布尔类型
# ══════════════════════════════════════════════════════════════


class BoolType(BaseType):
    """布尔类型 — 按 uint8 解析，输出 True/False。"""

    def __init__(self, name: str, path: str = "") -> None:
        super().__init__(name, path, bit_length=8)

    def deserialize(self, payload: bytes, offset: int, name: str) -> tuple[FieldNode, int]:
        node, consumed = super().deserialize(payload, offset, name)
        node.value = bool(node.value)
        return node, consumed


# ══════════════════════════════════════════════════════════════
# StringType — 变长字符串（UTF-8 / UTF-16 自适应）
# ══════════════════════════════════════════════════════════════


class StringType(DataType):
    """变长字符串。

    SOME/IP 格式：4 字节 BE 长度（字节数），之后是编码数据。
    自动识别 BOM：0xFEFF → UTF-16 BE，0xFFFE → UTF-16 LE，无 BOM → UTF-8。
    """

    def __init__(self, name: str, path: str = "") -> None:
        super().__init__(name, path)

    def deserialize(self, payload: bytes, offset: int, name: str) -> tuple[FieldNode, int]:
        if offset + 4 > len(payload):
            node = _import_field_node().leaf(
                name=name, type_name=self.name, value="<truncated>",
                offset=offset, raw=b"")
            return node, 0
        length = struct.unpack(">I", payload[offset:offset + 4])[0]
        consumed = 4 + length
        raw = payload[offset:offset + consumed]
        data = payload[offset + 4:offset + consumed]

        # BOM 检测
        if len(data) >= 2 and data[:2] == b'\xfe\xff':
            encoding = "utf-16-be"
            text = data[2:].decode(encoding, errors="replace")
        elif len(data) >= 2 and data[:2] == b'\xff\xfe':
            encoding = "utf-16-le"
            text = data[2:].decode(encoding, errors="replace")
        else:
            encoding = "utf-8"
            try:
                text = data.decode(encoding)
            except UnicodeDecodeError:
                text = raw[:32].hex() + ("..." if len(raw) > 32 else "")

        node = _import_field_node().leaf(
            name=name, type_name=self.name, value=text, offset=offset, raw=raw)
        return node, consumed

    @property
    def byte_size(self) -> int:
        return 0


# ══════════════════════════════════════════════════════════════
# StructureType — 结构体（流式位置推进）
# ══════════════════════════════════════════════════════════════


@dataclass
class StructField:
    """结构体字段。offset 仅用于编译期分析，反序列化时走流式推进。"""

    name: str
    type_ref: str
    resolved_type: DataType | None = None
    offset: int = 0

    @property
    def byte_size(self) -> int:
        if self.resolved_type is not None:
            return self.resolved_type.byte_size
        return 0


class StructureType(DataType):
    """结构体：流式反序列化，自动适应变长字段。"""

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

    def deserialize(self, payload: bytes, offset: int, name: str) -> tuple[FieldNode, int]:
        children: list[FieldNode] = []
        pos = offset
        for f in self.fields:
            if f.resolved_type is None:
                continue
            if pos >= len(payload):
                break
            child, consumed = f.resolved_type.deserialize(payload, pos, f.name)
            children.append(child)
            pos += consumed
        node = _import_field_node().container(
            name=name, type_name=self.name, offset=offset,
            byte_size=pos - offset, children=children)
        return node, pos - offset

    @property
    def byte_size(self) -> int:
        if not self.fields:
            return 0
        self.resolve_offsets()
        last = self.fields[-1]
        return last.offset + last.byte_size


# ══════════════════════════════════════════════════════════════
# ArrayType — 定长 ARRAY / 动态 VECTOR
# ══════════════════════════════════════════════════════════════


class ArrayType(DataType):
    """数组 / 向量。is_dynamic=True → VECTOR（4B BE 长度前缀）。"""

    def __init__(
        self, name: str, path: str = "", *,
        element_type_ref: str = "", element_type: DataType | None = None,
        length: int = 0, is_dynamic: bool = False,
    ) -> None:
        super().__init__(name, path)
        self.element_type_ref = element_type_ref
        self.element_type = element_type
        self.length = length
        self.is_dynamic = is_dynamic

    def deserialize(self, payload: bytes, offset: int, name: str) -> tuple[FieldNode, int]:
        children: list[FieldNode] = []
        pos = offset

        if self.is_dynamic:
            if pos + 4 > len(payload):
                node = _import_field_node().container(
                    name=name, type_name=self.name, offset=offset,
                    byte_size=0, children=[])
                return node, 0
            byte_len = struct.unpack(">I", payload[pos:pos + 4])[0]
            pos += 4
            end_pos = min(pos + byte_len, len(payload))
        else:
            byte_len = 0
            end_pos = len(payload)

        if self.element_type is not None:
            if self.is_dynamic:
                index = 0
                while pos < end_pos:
                    child, consumed = self.element_type.deserialize(
                        payload, pos, f"{name}[{index}]")
                    if consumed <= 0:
                        raise ValueError(
                            f"dynamic array element consumed {consumed} bytes for {self.name}")
                    next_pos = pos + consumed
                    if next_pos > end_pos:
                        raise ValueError(
                            f"dynamic array {self.name} overruns declared byte length {byte_len}")
                    children.append(child)
                    pos = next_pos
                    index += 1
            else:
                for i in range(self.length):
                    if pos >= len(payload):
                        break
                    child, consumed = self.element_type.deserialize(
                        payload, pos, f"{name}[{i}]")
                    children.append(child)
                    pos += consumed

        node = _import_field_node().container(
            name=name, type_name=self.name, offset=offset,
            byte_size=pos - offset, children=children)
        return node, pos - offset

    @property
    def byte_size(self) -> int:
        if self.element_type is not None:
            return self.element_type.byte_size * self.length
        return 0
    