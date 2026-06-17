"""
数据类型工厂。

根据 ArxmlParser 提取的原始类型描述，通过 **Factory + Builder 模式** 构建
可直接用于反序列化的 DataType 对象树。

设计模式：
    - **Factory Method**：``TypeFactory.create()`` 根据 ``category`` 分发到对应 Builder
    - **Builder**：每个 Builder 负责构造一种 DataType（BaseType / StructureType / ArrayType）
    - **Strategy**：``_TYPE_BUILDERS`` 注册表，新增类型只需添加条目，无需修改工厂逻辑
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from arxml_parser import RawDataType


# ======================================================================
# DataType 抽象基类与具体子类
# ======================================================================


class DataType(ABC):
    """反序列化数据类型的抽象基类。

    所有具体类型（基础类型、结构体、数组）都继承此类。
    """

    name: str
    path: str

    def __init__(self, name: str, path: str = "") -> None:
        self.name = name
        self.path = path

    @property
    @abstractmethod
    def byte_size(self) -> int:
        """类型占用的字节数。"""
        ...

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r} size={self.byte_size}>"


class BaseType(DataType):
    """基础类型：UINT8, UINT16, BOOLEAN 等。

    描述二进制编码方式：长度、字节序、有无符号。
    """

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
        return f"<{type(self).__name__} {sign}{self.bit_length} {self.name!r}>"


@dataclass
class StructField:
    """结构体中的一个字段。"""

    name: str
    type_ref: str      # 指向的 DataType 路径
    resolved_type: DataType | None = None  # build 完成后再填充
    offset: int = 0     # 在结构体中的字节偏移

    @property
    def byte_size(self) -> int:
        if self.resolved_type is not None:
            return self.resolved_type.byte_size
        return 0


class StructureType(DataType):
    """结构体类型：包含多个有序字段。"""

    def __init__(self, name: str, path: str = "") -> None:
        super().__init__(name, path)
        self.fields: list[StructField] = []

    def add_field(self, field: StructField) -> None:
        """添加字段（偏移在 resolve_fields 后计算）。"""
        self.fields.append(field)

    def resolve_offsets(self) -> None:
        """在所有字段的 resolved_type 填充完成后，计算偏移和总大小。"""
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

    def __repr__(self) -> str:
        fields_str = ", ".join(f.name for f in self.fields)
        return f"<StructureType {self.name!r} fields=[{fields_str}] size={self.byte_size}>"


class ArrayType(DataType):
    """数组类型：包含元素类型和长度。"""

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
        if self.element_type is not None and self.length > 0:
            return self.element_type.byte_size * self.length
        return 0


# ======================================================================
# Type Builder — 策略模式
# ======================================================================


class TypeBuilder(ABC):
    """某个 CATEGORY 的类型构建器基类（Strategy）。"""

    @abstractmethod
    def build(self, raw: RawDataType, factory: TypeFactory) -> DataType:
        """根据 ``raw`` 信息构建 ``DataType`` 并返回。"""
        ...


class _ValueTypeBuilder(TypeBuilder):
    """VALUE 类型构建器 → BaseType。"""

    # AUTOSAR 基础类型名 → (bit_length, is_signed) 的常用映射
    _BASE_TYPE_TABLE: ClassVar[dict[str, tuple[int, bool]]] = {
        "uint8": (8, False),
        "uint16": (16, False),
        "uint32": (32, False),
        "uint64": (64, False),
        "sint8": (8, True),
        "sint16": (16, True),
        "sint32": (32, True),
        "sint64": (64, True),
        "boolean": (8, False),
        "float32": (32, True),
        "float64": (64, True),
    }

    def build(self, raw: RawDataType, factory: TypeFactory) -> DataType:
        base_name = _last_segment(raw.base_type_ref or "uint8")
        bit_len, signed = self._BASE_TYPE_TABLE.get(
            base_name.lower(), (8, False)
        )
        return BaseType(
            name=raw.name,
            path=raw.path,
            bit_length=bit_len,
            is_signed=signed,
        )


class _StructureTypeBuilder(TypeBuilder):
    """STRUCTURE 类型构建器 → StructureType。"""

    def build(self, raw: RawDataType, factory: TypeFactory) -> DataType:
        st = StructureType(name=raw.name, path=raw.path)
        for sub in raw.sub_elements:
            field = StructField(name=sub.name, type_ref=sub.type_ref)
            st.add_field(field)
        return st


class _ArrayTypeBuilder(TypeBuilder):
    """ARRAY 类型构建器 → ArrayType。"""

    def build(self, raw: RawDataType, factory: TypeFactory) -> DataType:
        elem_ref = raw.array_element.type_ref if raw.array_element else ""
        return ArrayType(
            name=raw.name,
            path=raw.path,
            element_type_ref=elem_ref,
        )


# ======================================================================
# Type Factory
# ======================================================================


class TypeFactory:
    """根据 ArxmlParser 的原始输出构建 DataType 对象池。

    扩展新类型只需在 ``_BUILDERS`` 中加一行。
    """

    _BUILDERS: ClassVar[dict[str, TypeBuilder]] = {
        "VALUE": _ValueTypeBuilder(),
        "STRUCTURE": _StructureTypeBuilder(),
        "ARRAY": _ArrayTypeBuilder(),
    }

    def __init__(self) -> None:
        self._types: dict[str, DataType] = {}

    # ---- 公开接口 ----

    def build_all(self, raw_types: list[RawDataType]) -> dict[str, DataType]:
        """批量构建所有数据类型。

        Returns
        -------
        dict[str, DataType]
            ``{type_path: DataType}`` 的类型对象池。
        """
        self._types.clear()

        # 第一遍：创建所有类型骨架
        for raw in raw_types:
            path = raw.path or self._resolve_path(raw.name)
            builder = self._BUILDERS.get(raw.category)
            if builder is not None:
                self._types[path] = builder.build(raw, self)

        # 第二遍：解析引用（StructureType 的字段 → 实际 DataType）
        for dt in self._types.values():
            if isinstance(dt, StructureType):
                for field in dt.fields:
                    field.resolved_type = self.resolve(field.type_ref)
                dt.resolve_offsets()
            elif isinstance(dt, ArrayType):
                dt.element_type = self.resolve(dt.element_type_ref)

        return self._types

    def resolve(self, type_ref: str) -> DataType | None:
        """根据 TYPE-REF 路径查找已构建的 DataType。"""
        if not type_ref:
            return None
        # 精确匹配
        if type_ref in self._types:
            return self._types[type_ref]
        # 去掉 /Package 前缀再匹配
        alt = type_ref[8:] if type_ref.startswith("/Package") else f"/Package{type_ref}"
        if alt in self._types:
            return self._types[alt]
        # 短名称 fallback
        short = _last_segment(type_ref)
        for path, dt in self._types.items():
            if path.endswith(f"/{short}"):
                return dt
        return None

    # ---- 内部工具 ----

    @staticmethod
    def _resolve_path(name: str) -> str:
        return f"/Package/{name}"


def _last_segment(ref: str) -> str:
    """从路径 /A/B/C 中提取最后一段 C。"""
    return ref.rstrip("/").rsplit("/", 1)[-1]
