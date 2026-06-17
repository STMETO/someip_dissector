"""
数据类型工厂。

根据 ArxmlParser 提取的原始描述，构建可直接反序列化的 DataType 对象池。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from .arxml_parser import RawBaseType, RawDataType
from .data_types import (
    ArrayType,
    BaseType,
    DataType,
    StringType,
    StructField,
    StructureType,
)


# ======================================================================
# Type Builder 策略
# ======================================================================
# 采用策略模式，把「不同 ARXML 类别构建 DataType 对象」的逻辑拆分成独立类：
    # TypeBuilder：抽象策略基类，统一约束所有类型构建器的接口
    # 5 个带下划线私有实现类：分别对应 RawDataType.category 的 5 种分类（VALUE / TYPE_REFERENCE / STRUCTURE / VECTOR/ARRAY/ STRING）；
    # 解耦逻辑：TypeFactory 不需要写一堆 if/elif 判断，只通过 category 匹配对应 Builder，新增类型只需要新增 Builder，符合开闭原则。

# raw: RawDataType：ArxmlParser 输出的原始 XML 类型数据；
# factory: TypeFactory：工厂主对象，提供基础类型查找、路径解析等工具能力；
# 返回：完整骨架 DataType 对象
class TypeBuilder(ABC):
    @abstractmethod
    def build(self, raw: RawDataType, factory: TypeFactory) -> DataType: ...


class _ValueBuilder(TypeBuilder):
    """处理 CATEGORY="VALUE" 类型
    VALUE：简单包装SW-BASE-TYPE，等价C语言typedef uint32_t MyUint32;
    作用：根据类型名称匹配底层SW-BASE-TYPE，生成完整BaseType基础类型对象
    """

    def build(self, raw: RawDataType, factory: TypeFactory) -> DataType:
        # 通过工厂查找该类型名对应的底层SW-BASE-TYPE原始数据
        bt = factory.resolve_base_type(raw.name)
        if bt is not None:
            # 匹配到基础类型，封装为可计算的BaseType运行时对象
            return BaseType(
                name=raw.name, path=raw.path,
                bit_length=bt.bit_size,         # # 从SW-BASE-TYPE读取比特长度
                byte_order=_map_byte_order(bt.byte_order),
                # # 根据名称判断是否有符号：int/sint开头为有符号
                is_signed="int" in bt.name.lower() or "sint" in bt.name.lower(),
            )
        # 兜底：匹配失败返回默认32位基础类型，防止解析中断
        return BaseType(name=raw.name, path=raw.path, bit_length=32)


class _TypeReferenceBuilder(TypeBuilder):
    """处理 CATEGORY="TYPE_REFERENCE" 类型
        TYPE_REFERENCE：类型别名，仅引用另一个已定义的复合类型
        第一遍解析无法直接拿到目标DataType，因此先创建空占位BaseType；
        第三遍工厂统一遍历替换占位符，完成引用跳转解析
    """

    def build(self, raw: RawDataType, factory: TypeFactory) -> DataType:
        # bit_length=0 作为占位标记，工厂后续识别并替换为真实类型
        return BaseType(name=raw.name, path=raw.path, bit_length=0)


class _StructureBuilder(TypeBuilder):
    """处理 CATEGORY="STRUCTURE" 结构体类型
        读取RawDataType内所有子字段RawSubElement，创建空StructField存入结构体
        仅记录字段名称与原始type_ref字符串，不解析字段真实类型（第二遍工厂统一解析
    """

    def build(self, raw: RawDataType, factory: TypeFactory) -> DataType:
        st = StructureType(name=raw.name, path=raw.path)
        for sub in raw.sub_elements:
            st.add_field(StructField(name=sub.name, type_ref=sub.type_ref))
        return st


class _VectorArrayBuilder(TypeBuilder):
    """处理 CATEGORY="VECTOR" / "ARRAY"
    ARRAY：定长静态数组；VECTOR：SOME/IP动态向量（带最大长度限制）
    仅记录元素类型引用字符串、数组长度，不解析元素真实DataType
    """
    def build(self, raw: RawDataType, factory: TypeFactory) -> DataType:
        return ArrayType(
            name=raw.name, 
            path=raw.path,
            element_type_ref=raw.type_ref,  # 原始元素类型路径，待二次解析
            element_type=None,              # 元素真实类型留空
            length=raw.array_size,          # 数组/向量最大长度
        )



class _StringBuilder(TypeBuilder):
    """处理 CATEGORY="STRING" 变长字符串类型
    SOME/IP字符串为动态长度，静态无法计算字节大小，单独封装StringType
    """
    def build(self, raw: RawDataType, factory: TypeFactory) -> DataType:
        return StringType(name=raw.name, path=raw.path)



# ======================================================================
# Type Factory
# ======================================================================

class TypeFactory:
    """根据解析结果构建 DataType 对象池。"""

    # 策略模式映射表：category字符串 → 对应构建器实例
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
        # 缓存所有底层SW-BASE-TYPE原始数据，key=基础类型短名
        self._base_types: dict[str, RawBaseType] = {}
        # 别名映射：TYPE_REFERENCE类型完整路径 → 它引用的目标类型路径
        self._alias: dict[str, str] = {}

    # ---- 公开 ----

    def build_all(
        self,
        base_types: list[RawBaseType],
        impl_types: list[RawDataType],
    ) -> dict[str, DataType]:
        # 清空上次缓存，支持重复调用构建
        self._types.clear()
        # 将基础类型列表转为字典，方便按名称快速查询
        self._base_types = {bt.name: bt for bt in base_types}
        self._alias.clear()

        # ========== 第一遍：仅创建所有类型骨架，收集别名映射 ==========
        for raw in impl_types:
            # 获取类型完整AR路径，为空则生成默认标准路径
            path = raw.path or self._resolve_path(raw.name)
            # 如果当前是TYPE_REFERENCE别名类型，记录【当前路径→目标引用路径】
            if raw.category == "TYPE_REFERENCE" and raw.type_ref:
                self._alias[path] = raw.type_ref
            # 根据category匹配对应Builder，创建空骨架DataType
            builder = self._BUILDERS.get(raw.category)
            if builder is not None:
                self._types[path] = builder.build(raw, self)

        # ========== 第二遍：填充结构体/数组内部字段的真实类型引用 ==========
        for dt in self._types.values():
            # 结构体：遍历所有字段，解析type_ref拿到真实DataType，计算字段偏移
            if isinstance(dt, StructureType):
                for f in dt.fields:
                    # 递归穿透所有别名链，找到字段最终指向的真实类型
                    f.resolved_type = self._resolve_chain(f.type_ref)
                # 根据每个字段尺寸自动计算offset偏移
                dt.resolve_offsets()
            # 数组/向量：解析元素类型引用，赋值element_type
            elif isinstance(dt, ArrayType):
                dt.element_type = self._resolve_chain(dt.element_type_ref)

        # ========== 第三遍：替换TYPE_REFERENCE生成的空占位符 ==========
        # list(self._types.items()) 防止遍历过程中修改字典报错
        for path, dt in list(self._types.items()):
            # 识别占位标记：BaseType且bit_length=0 代表TYPE_REFERENCE临时占位
            if isinstance(dt, BaseType) and dt.bit_length == 0:
                # 递归解析该别名路径对应的真实类型
                resolved = self._resolve_chain(path)
                # 找到有效非占位类型，替换掉字典里的占位对象
                if resolved is not None and not _is_placeholder(resolved):
                    self._types[path] = resolved

        # 返回全局完整类型池
        return self._types


    def _resolve_chain(self, type_ref: str) -> DataType | None:
        """跟踪别名链返回最终 DataType。
        输入可以是 TYPE-REFERENCE 类型的路径，也可以是字段/元素的 type_ref。
        自动穿透 TYPE_REFERENCE → VALUE → SW-BASE-TYPE 的引用链。
        """
        # 空引用直接返回空
        if not type_ref:
            return None
        cur = type_ref
        seen: set[str] = set()
        # 最多循环10次，防止循环引用无限递归死循环
        for _ in range(10):
            # 出现循环引用，终止解析
            if cur in seen:
                break
            seen.add(cur)

            # 1. 先根据路径查找全局类型池
            dt = self._lookup(cur)
            if dt is None:
                # 没找到类型，尝试走别名跳转
                alias_target = self._alias.get(cur)
                if alias_target and alias_target != cur:
                    cur = alias_target
                    continue
                # 既找不到、也无别名，返回空
                return None

            # 2. 判断当前类型是否已经是完整可用类型，直接返回
            if isinstance(dt, StringType):
                return dt
            if isinstance(dt, BaseType) and dt.bit_length > 0:
                return dt
            if isinstance(dt, (StructureType, ArrayType)):
                return dt

            # 3. 当前是占位符BaseType，继续走别名跳转
            alias_target = self._alias.get(cur) or self._alias.get(dt.path)
            if alias_target and alias_target != cur:
                cur = alias_target
                continue

            # 4. 兜底：别名链走完，尝试匹配底层SW-BASE-TYPE基础类型
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

        # 解析失败兜底：返回未解析占位类型，避免代码抛None异常
        return BaseType(name="unresolved", path=cur, bit_length=0)


    def _lookup(self, type_ref: str) -> DataType | None:
        """按路径精确查找，失败则尝试短名称尾匹配。"""
        # 优先精确匹配完整AR路径（标准规范写法）
        if type_ref in self._types:
            return self._types[type_ref]
        # 截取路径最后一段短名，兼容只传类型名不完整路径的场景
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
        # 1. 精确匹配
        if impl_name in self._base_types:
            return self._base_types[impl_name]
        # 2. 去除标准后缀 _t 再匹配（AUTOSAR惯例：uint32_t）
        stripped = impl_name.removesuffix("_t")
        if stripped in self._base_types:
            return self._base_types[stripped]
        # 3. 忽略大小写模糊匹配兜底
        for name, bt in self._base_types.items():
            if name.lower() == stripped.lower():
                return bt
        return None


    @staticmethod
    def _resolve_path(name: str) -> str:
        # AR标准默认实现数据类型存放路径
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
