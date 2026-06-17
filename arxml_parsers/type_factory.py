"""
数据类型工厂。

根据 ArxmlParser 提取的原始描述，构建可直接反序列化的 DataType 对象池。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from arxml_parser import RawBaseType, RawDataType, RawSubElement


# ======================================================================
# DataType 体系
# ======================================================================


class DataType(ABC):
    """反序列化数据类型的抽象基类。"""

    def __init__(self, name: str, path: str = "") -> None:
        self.name = name
        self.path = path

    @property
    @abstractmethod
    def byte_size(self) -> int: ...

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r} size={self.byte_size}>"


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


class StringType(DataType):
    """变长字符串 — 字节数由运行时数据决定。"""

    def __init__(self, name: str, path: str = "") -> None:
        super().__init__(name, path)

    @property
    def byte_size(self) -> int:
        return 0  # 变长，编译时不可知


@dataclass
class StructField:
    """结构体中的一个字段。"""

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
    """结构体：包含有序字段。"""

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


class ArrayType(DataType):
    """数组/向量类型。"""

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


# ======================================================================
# Type Builder 策略
# ======================================================================

class TypeBuilder(ABC):
    @abstractmethod
    def build(self, raw: RawDataType, factory: TypeFactory) -> DataType: ...


class _ValueBuilder(TypeBuilder):
    """VALUE 类型：根据 short_name 匹配 SW-BASE-TYPE。"""

    def build(self, raw: RawDataType, factory: TypeFactory) -> DataType:
        bt = factory.resolve_base_type(raw.name)
        if bt is not None:
            return BaseType(
                name=raw.name, path=raw.path,
                bit_length=bt.bit_size,
                byte_order=_map_byte_order(bt.byte_order),
                is_signed="int" in bt.name.lower() or "sint" in bt.name.lower(),
            )
        return BaseType(name=raw.name, path=raw.path, bit_length=32)


class _TypeReferenceBuilder(TypeBuilder):
    """TYPE_REFERENCE：仅存引用，等待第二遍解析。"""

    def build(self, raw: RawDataType, factory: TypeFactory) -> DataType:
        # 创建一个占位 BaseType，第二遍时替换
        return BaseType(name=raw.name, path=raw.path, bit_length=0)


class _StructureBuilder(TypeBuilder):
    """STRUCTURE 类型。"""

    def build(self, raw: RawDataType, factory: TypeFactory) -> DataType:
        st = StructureType(name=raw.name, path=raw.path)
        for sub in raw.sub_elements:
            st.add_field(StructField(name=sub.name, type_ref=sub.type_ref))
        return st


class _VectorArrayBuilder(TypeBuilder):
    """VECTOR / ARRAY 类型。"""

    def build(self, raw: RawDataType, factory: TypeFactory) -> DataType:
        return ArrayType(
            name=raw.name, path=raw.path,
            element_type_ref=raw.type_ref,
            length=raw.array_size,
        )


class _StringBuilder(TypeBuilder):
    """STRING 类型 — 变长，字节数在运行时确定。"""

    def build(self, raw: RawDataType, factory: TypeFactory) -> DataType:
        return StringType(name=raw.name, path=raw.path)


# ======================================================================
# Type Factory
# ======================================================================

class TypeFactory:
    """根据解析结果构建 DataType 对象池。"""

    _BUILDERS: ClassVar[dict[str, TypeBuilder]] = {
        "VALUE": _ValueBuilder(),
        "TYPE_REFERENCE": _TypeReferenceBuilder(),
        "STRUCTURE": _StructureBuilder(),
        "VECTOR": _VectorArrayBuilder(),
        "ARRAY": _VectorArrayBuilder(),
        "STRING": _StringBuilder(),
    }

    def __init__(self) -> None:
        self._types: dict[str, DataType] = {}
        self._base_types: dict[str, RawBaseType] = {}
        self._alias: dict[str, str] = {}    # TYPE_REFERENCE path → target_ref

    # ---- 公开 ----

    def build_all(
        self,
        base_types: list[RawBaseType],
        impl_types: list[RawDataType],
    ) -> dict[str, DataType]:
        self._types.clear()
        self._base_types = {bt.name: bt for bt in base_types}
        self._alias.clear()

        # ── 第一遍：创建骨架 + 收集 TYPE_REFERENCE 别名 ──
        for raw in impl_types:
            path = raw.path or self._resolve_path(raw.name)
            if raw.category == "TYPE_REFERENCE" and raw.type_ref:
                self._alias[path] = raw.type_ref
            builder = self._BUILDERS.get(raw.category)
            if builder is not None:
                self._types[path] = builder.build(raw, self)

        # ── 第二遍：解析 Struct/Array 的字段引用 ──
        for dt in self._types.values():
            if isinstance(dt, StructureType):
                for f in dt.fields:
                    f.resolved_type = self._resolve_chain(f.type_ref)
                dt.resolve_offsets()
            elif isinstance(dt, ArrayType):
                dt.element_type = self._resolve_chain(dt.element_type_ref)

        # ── 第三遍：替换 TYPE_REFERENCE 占位符 ──
        for path, dt in list(self._types.items()):
            if isinstance(dt, BaseType) and dt.bit_length == 0:
                resolved = self._resolve_chain(path)
                if resolved is not None and not _is_placeholder(resolved):
                    self._types[path] = resolved

        return self._types

    def _resolve_chain(self, type_ref: str) -> DataType | None:
        """跟踪别名链返回最终 DataType。

        输入可以是 TYPE-REFERENCE 类型的路径，也可以是字段/元素的 type_ref。
        自动穿透 TYPE_REFERENCE → VALUE → SW-BASE-TYPE 的引用链。
        """
        if not type_ref:
            return None
        cur = type_ref
        seen: set[str] = set()
        for _ in range(10):  # 防无限循环
            if cur in seen:
                break
            seen.add(cur)

            # 1. 直接查找
            dt = self._lookup(cur)
            if dt is None:
                # 未找到：可能 cur 是别名路径，尝试通过 _alias 首次跳转
                alias_target = self._alias.get(cur)
                if alias_target and alias_target != cur:
                    cur = alias_target
                    continue
                return None

            # 2. 非占位符 → 已解析，返回
            if isinstance(dt, StringType):
                return dt
            if isinstance(dt, BaseType) and dt.bit_length > 0:
                return dt
            if isinstance(dt, (StructureType, ArrayType)):
                return dt

            # 3. BaseType(bit_length==0) 占位符 → 通过 _alias 跳转到目标
            alias_target = self._alias.get(cur) or self._alias.get(dt.path)
            if alias_target and alias_target != cur:
                cur = alias_target
                continue

            # 4. 最后兜底：用短名（去掉 _t）匹配 SW-BASE-TYPE
            bare_name = dt.name.removesuffix("_t")
            bt = self.resolve_base_type(bare_name)
            if bt is not None and bt.bit_size > 0:
                return BaseType(
                    name=dt.name, path=dt.path,
                    bit_length=bt.bit_size,
                    byte_order=_map_byte_order(bt.byte_order),
                    is_signed="int" in bt.name.lower(),
                )
            break

        return BaseType(name="unresolved", path=cur, bit_length=0)  # 兜底，避免 None

    def _lookup(self, type_ref: str) -> DataType | None:
        """按路径精确查找，失败则尝试短名称尾匹配。"""
        if type_ref in self._types:
            return self._types[type_ref]
        short = _last_segment(type_ref)
        for path, dt in self._types.items():
            if path.endswith(f"/{short}"):
                return dt
        return None

    # -- deprecated alias, kept for compatibility --
    follow_alias = _resolve_chain
    resolve = _lookup

    def resolve_base_type(self, impl_name: str) -> RawBaseType | None:
        """根据实现类型名查找对应的 SW-BASE-TYPE。

        策略：去掉 `_t` 后缀匹配，如 int32_t → int32。
        """
        # 精确匹配
        if impl_name in self._base_types:
            return self._base_types[impl_name]
        # 去 _t 后缀
        stripped = impl_name.removesuffix("_t")
        if stripped in self._base_types:
            return self._base_types[stripped]
        # partial match
        for name, bt in self._base_types.items():
            if name.lower() == stripped.lower():
                return bt
        return None

    @staticmethod
    def _resolve_path(name: str) -> str:
        return f"/DataTypes/ImplementationDataTypes/{name}"


# ======================================================================
# 工具
# ======================================================================

def _last_segment(ref: str) -> str:
    return ref.rstrip("/").rsplit("/", 1)[-1]


def _is_placeholder(dt: DataType) -> bool:
    """判断是否为占位类型（需要继续解析）。"""
    return isinstance(dt, BaseType) and dt.bit_length == 0


def _map_byte_order(bo: str) -> str:
    m = bo.upper()
    if "LITTLE" in m:
        return "little"
    return "big"  # OPAQUE / BIG-ENDIAN / MOST-SIGNIFICANT → big
