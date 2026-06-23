"""
ARXML 原始数据提取器（适配 AUTOSAR Adaptive 真实格式）。

使用 lxml 解析 ARXML 文件，提取：
1. SW-BASE-TYPE — 基础类型（大小、字节序、编码）
2. STD-CPP-IMPLEMENTATION-DATA-TYPE — C++ 实现类型
3. SERVICE-INTERFACE — 服务接口（方法参数+方向+类型引用）
4. SOMEIP-SERVICE-INTERFACE-DEPLOYMENT — SOME/IP 部署映射
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree
from utils.logger import get_logger

logger = get_logger(__name__)

# AUTOSAR R4.0 标准 XML 命名空间 URI（ARXML 文件根节点固定声明）
_AR_NS = "http://autosar.org/schema/r4.0"

# 命名空间映射字典，给 XPath 查询起别名：key ns：自定义命名空间前缀；
_NSMAP = {"ns": _AR_NS}


# ======================================================================
# 数据类
# ======================================================================

# 基础类型相关（AUTOSAR 数据类型体系）
# @dataclass：装饰器，自动生成构造函数、__repr__、__eq__，不用手写初始化
@dataclass
class RawBaseType:
    """SW-BASE-TYPE 原始信息。"""
    # 对应 ARXML 节点：<SW-BASE-TYPE>

    name: str               # 类型短名，如 uint32
    path: str = ""          # ARXML 完整对象路径，如 /DataTypes/SwBaseTypes/uint32，用于全局索引查找
    bit_size: int = 0       # 占用比特数，uint32 就是 32
    encoding: str = ""      # 编码方式，如 TWOS_COMPLEMENT（补码）、IEEE754 浮点
    byte_order: str = ""    # OPAQUE(二进制不透传) | BIG-ENDIAN | LITTLE-ENDIAN

@dataclass
class RawSubElement:
    """STRUCTURE / CPP-IMPLEMENTATION-DATA-TYPE-ELEMENT 中的一个字段。"""
    # 对应节点：<CPP-IMPLEMENTATION-DATA-TYPE-ELEMENT>
    # 结构体里面的单个字段，仅用于 RawDataType 结构体分类下的子项。

    name: str           # 结构体字段名
    type_ref: str       # 字符串路径，指向该字段引用的数据类型

@dataclass
class RawDataType:
    """一个 STD-CPP-IMPLEMENTATION-DATA-TYPE 的原始信息。"""
    # 对应节点：<STD-CPP-IMPLEMENTATION-DATA-TYPE>
    # AUTOSAR Adaptive 上层复合数据类型，分 5 种类别由 category 区分

    name: str
    path: str = ""
    category: str = ""          # TYPE_REFERENCE | VALUE | STRUCTURE | VECTOR | ARRAY
    type_ref: str = ""           # TYPE-REFERENCE-REF 或 TEMPLATE-TYPE-REF
    array_size: int = 0          # VECTOR / ARRAY
    sub_elements: list[RawSubElement] = field(default_factory=list) # 结构体成员列表


# 服务接口层（SERVICE-INTERFACE，业务 API 定义）
@dataclass
class RawMethodArg:
    """ARGUMENT-DATA-PROTOTYPE 的原始信息。"""
    # 对应节点：<ARGUMENT-DATA-PROTOTYPE>，接口方法的单个入参 / 出参
    name: str            # 参数名
    type_ref: str        # 参数绑定的数据类型路径
    direction: str = ""  # IN | OUT | INOUT


@dataclass
class RawServiceMethod:
    """一个 CLIENT-SERVER-OPERATION 的参数信息。"""
    # 对应节点：<CLIENT-SERVER-OPERATION>，服务里的一个 RPC 方法（客户端调用、服务端响应）

    name: str       # 方法名
    arguments: list[RawMethodArg] = field(default_factory=list) # 该方法所有参数列表


@dataclass
class RawServiceEvent:
    """一个 VARIABLE-DATA-PROTOTYPE 的原始信息。"""
    # 对应节点：<VARIABLE-DATA-PROTOTYPE>  服务广播事件（服务端主动推送，客户端订阅）

    name: str           # 事件名称
    type_ref: str       # 事件携带的数据类型


@dataclass
class RawServiceInterface:
    """一个 SERVICE-INTERFACE 的完整信息。"""
    # 对应节点：<SERVICE-INTERFACE>，完整服务接口，一组 RPC 方法 + 广播事件的集合

    name: str           # 接口名称
    path: str           # 全局路径
    methods: dict[str, RawServiceMethod] = field(default_factory=dict)  # 字典 key = 方法名，快速按名称查找方法
    events: dict[str, RawServiceEvent] = field(default_factory=dict)    # 字典 key = 事件名，快速按名称查找事件


# SOME/IP 部署 ID 映射层（网络传输层配置）
@dataclass
class RawMethodDeployment:
    # 单个方法的 SOME/IP ID 绑定
    method_id: int      # method_id：SOME/IP MethodID（数字）
    method_ref: str     # 字符串路径，关联前面定义的 RawServiceMethod


@dataclass
class RawEventDeployment:
    # 单个事件的 SOME/IP ID 绑定
    event_id: int   # SOME/IP EventID（数字）
    event_ref: str  # 关联事件对象路径


@dataclass
class RawEventGroupDeployment:
    """单个 EventGroup 的 SOME/IP 部署。"""
    event_group_id: int     # EventGroup ID
    name: str = ""          # SHORT-NAME (e.g. ADCC_RtMM_Eventgroup)


@dataclass
class RawServiceDeployment:
    """对应节点：<SOMEIP-SERVICE-INTERFACE-DEPLOYMENT>。"""
    service_id: int
    interface_ref: str
    methods: list[RawMethodDeployment] = field(default_factory=list)
    events: list[RawEventDeployment] = field(default_factory=list)
    event_groups: list[RawEventGroupDeployment] = field(default_factory=list)


# ======================================================================
# Parser
# ======================================================================


class ArxmlParser:
    """解析 ARXML 文件，提取原始数据。"""

    def __init__(self, filepath: str | Path):
        self.filepath = Path(filepath)
        self._root: etree._Element | None = None

        self.raw_base_types: list[RawBaseType] = []             # 全部底层基础类型 uint8/int32...
        self.raw_types: list[RawDataType] = []                  # 全部结构体、数组、vector 自定义类型
        self.raw_interfaces: list[RawServiceInterface] = []     # 全部服务接口（方法 + 事件）
        self.raw_deployments: list[RawServiceDeployment] = []   # 全部 SOME/IP ID 部署映射

    # ---- 公开接口 ----

    # 唯一给外部调用的方法，固定线性解析流程
    def parse(self) -> None:
        logger.info("Loading ARXML: %s", self.filepath)
        self._load_xml()

        self.raw_base_types = self._extract_base_types()
        logger.info("Extracted %d SW-BASE-TYPEs", len(self.raw_base_types))

        self.raw_types = self._extract_impl_types()
        logger.info("Extracted %d implementation types", len(self.raw_types))

        self.raw_interfaces = self._extract_service_interfaces()
        logger.info("Extracted %d service interfaces", len(self.raw_interfaces))

        self.raw_deployments = self._extract_deployments()
        logger.info("Extracted %d SOME/IP deployments", len(self.raw_deployments))

    # _load_xml () 加载 XML 文件
    def _load_xml(self) -> None:
        self._root = etree.parse(   # lxml 加载文件，生成 DOM 树
            str(self.filepath), etree.XMLParser(remove_blank_text=True)
        ).getroot()

    # ==================================================================
    # BASE TYPE（SW-BASE-TYPE）
    # ==================================================================

    def _extract_base_types(self) -> list[RawBaseType]:
        # XPath 全局查找所有 <SW-BASE-TYPE> 节点：.//ns:SW-BASE-TYPE
        # .// 代表递归查找整个文档所有层级，不用关心节点在 XML 哪个位置
        elements = self._root.findall(".//ns:SW-BASE-TYPE", _NSMAP)
        result = []
        # 遍历每个节点，依次提取：SHORT-NAME、完整路径、位宽、编码、字节序
        for elem in elements:
            name = self._child_text(elem, "SHORT-NAME") or ""
            path = self._resolve_ref_path(elem)
            size_str = self._child_text(elem, "BASE-TYPE-SIZE") or "0"
            result.append(RawBaseType(
                name=name,
                path=path,
                bit_size=int(size_str),
                encoding=self._child_text(elem, "BASE-TYPE-ENCODING") or "",
                byte_order=self._child_text(elem, "BYTE-ORDER") or "",
            ))
        return result

    # ==================================================================
    # IMPLEMENTATION TYPE（STD-CPP-IMPLEMENTATION-DATA-TYPE）
    # ==================================================================
    # AUTOSAR 复合类型，根据 CATEGORY 分支处理不同结构
    def _extract_impl_types(self) -> list[RawDataType]:
        elements = self._root.findall(
            ".//ns:STD-CPP-IMPLEMENTATION-DATA-TYPE", _NSMAP
        )
        result = []
        for elem in elements:
            name = self._child_text(elem, "SHORT-NAME") or ""
            category = self._child_text(elem, "CATEGORY") or ""
            path = self._resolve_ref_path(elem)
            rd = RawDataType(name=name, path=path, category=category)

            if category == "TYPE_REFERENCE":    # 简单引用其他类型，只存 type_ref
                rd.type_ref = self._child_text(elem, "TYPE-REFERENCE-REF") or ""
            elif category == "STRUCTURE":       # 调用子函数 _extract_struct_elements 提取结构体所有字段，生成 RawSubElement 列表
                rd.sub_elements = self._extract_struct_elements(elem)
            elif category in ("VECTOR", "ARRAY"):   # 读取数组长度，调用 _child_text_deep 多层嵌套读取模板内部类型引用
                rd.array_size = int(self._child_text(elem, "ARRAY-SIZE") or "0")
                rd.type_ref = self._extract_template_type_ref(elem)

            result.append(rd)
        return result

    def _extract_struct_elements(self, elem: etree._Element) -> list[RawSubElement]:
        """提取 STRUCTURE 的子元素（CPP-IMPLEMENTATION-DATA-TYPE-ELEMENT）。"""
        subs = []
        for sub in elem.findall(
            ".//ns:CPP-IMPLEMENTATION-DATA-TYPE-ELEMENT", _NSMAP
        ):
            name = self._child_text(sub, "SHORT-NAME") or ""
            # TYPE-REFERENCE-REF 嵌套在 TYPE-REFERENCE 内
            type_ref_elem = sub.find("ns:TYPE-REFERENCE", _NSMAP)
            if type_ref_elem is not None:
                type_ref = self._child_text(type_ref_elem, "TYPE-REFERENCE-REF") or ""
            else:
                type_ref = self._child_text(sub, "TYPE-REFERENCE-REF") or ""
            if name and type_ref:
                subs.append(RawSubElement(name=name, type_ref=type_ref))
        return subs

    def _extract_template_type_ref(self, elem: etree._Element) -> str:
        """提取 VECTOR/ARRAY 的 TEMPLATE-TYPE-REF。"""
        return self._child_text_deep(elem, ["TEMPLATE-ARGUMENTS",
            "CPP-TEMPLATE-ARGUMENT", "TEMPLATE-TYPE-REF"])

    # ==================================================================
    # SERVICE INTERFACE
    # ==================================================================
    # 解析业务服务接口，分两部分：方法 + 事件
    def _extract_service_interfaces(self) -> list[RawServiceInterface]:
        elements = self._root.findall(".//ns:SERVICE-INTERFACE", _NSMAP)
        result = []
        for elem in elements:
            name = self._child_text(elem, "SHORT-NAME") or ""
            path = self._resolve_ref_path(elem)
            iface = RawServiceInterface(name=name, path=path)

            # 方法
            for op in elem.findall(".//ns:CLIENT-SERVER-OPERATION", _NSMAP):
                method = self._extract_method(op)
                iface.methods[method.name] = method

            # 事件
            for evt in elem.findall(
                "./ns:EVENTS/ns:VARIABLE-DATA-PROTOTYPE", _NSMAP
            ):
                evt_name = self._child_text(evt, "SHORT-NAME") or ""
                evt_type_ref = (
                    self._child_text(evt, "TYPE-TREF")
                    or self._child_text(evt, "TYPE-REF")
                    or ""
                )
                if evt_name:
                    iface.events[evt_name] = RawServiceEvent(
                        name=evt_name, type_ref=evt_type_ref
                    )

            result.append(iface)
        return result

    def _extract_method(self, op_elem: etree._Element) -> RawServiceMethod:
        name = self._child_text(op_elem, "SHORT-NAME") or ""
        method = RawServiceMethod(name=name)
        for arg in op_elem.findall(".//ns:ARGUMENT-DATA-PROTOTYPE", _NSMAP):
            arg_name = self._child_text(arg, "SHORT-NAME") or ""
            # 真实 ARXML 用 TYPE-TREF（不是 TYPE-REF）
            arg_type_ref = (
                self._child_text(arg, "TYPE-TREF")
                or self._child_text(arg, "TYPE-REF")
                or ""
            )
            direction = self._child_text(arg, "DIRECTION") or ""
            if arg_name and arg_type_ref:
                method.arguments.append(RawMethodArg(
                    name=arg_name, type_ref=arg_type_ref, direction=direction
                ))
        return method

    # ==================================================================
    # DEPLOYMENT
    # ==================================================================
    # 网络通信 ID 配置，和上层接口解耦：
    def _extract_deployments(self) -> list[RawServiceDeployment]:
        elements = self._root.findall(
            ".//ns:SOMEIP-SERVICE-INTERFACE-DEPLOYMENT", _NSMAP
        )
        result = []
        for elem in elements:
            # 真实标签是 SERVICE-INTERFACE-ID（不是 SERVICE-ID）
            srv_id_str = (
                self._child_text(elem, "SERVICE-INTERFACE-ID")
                or self._child_text(elem, "SERVICE-ID")
                or "0"
            )
            iface_ref = (
                self._child_text(elem, "SERVICE-INTERFACE-REF") or ""
            )

            dep = RawServiceDeployment(
                service_id=int(srv_id_str),
                interface_ref=iface_ref,
            )

            for md in elem.findall(
                ".//ns:SOMEIP-METHOD-DEPLOYMENT", _NSMAP
            ):
                mid_str = self._child_text(md, "METHOD-ID") or "0"
                mref = self._child_text(md, "METHOD-REF") or ""
                dep.methods.append(
                    RawMethodDeployment(method_id=int(mid_str), method_ref=mref)
                )

            for ed in elem.findall(
                ".//ns:SOMEIP-EVENT-DEPLOYMENT", _NSMAP
            ):
                eid_str = self._child_text(ed, "EVENT-ID") or "0"
                eref = self._child_text(ed, "EVENT-REF") or ""
                dep.events.append(
                    RawEventDeployment(event_id=int(eid_str), event_ref=eref)
                )

            for eg in elem.findall(
                ".//ns:SOMEIP-EVENT-GROUP", _NSMAP
            ):
                eg_id_str = self._child_text(eg, "EVENT-GROUP-ID") or "0"
                eg_name = self._child_text(eg, "SHORT-NAME") or ""
                dep.event_groups.append(
                    RawEventGroupDeployment(
                        event_group_id=int(eg_id_str), name=eg_name)
                )

            result.append(dep)
        return result

    # ==================================================================
    # 工具方法
    # ==================================================================

    @staticmethod
    # 获取当前节点下直接子标签的文本，自动处理空值、去除首尾空格
    def _child_text(elem: etree._Element, tag: str) -> str | None:
        child = elem.find(f"ns:{tag}", _NSMAP)
        return child.text.strip() if child is not None and child.text else None

    @staticmethod
    # 多层嵌套标签穿透读取，例如 ["A","B","C"]，逐层向下查找子节点，中间任意一层不存在直接返回空字符串。
    def _child_text_deep(
        elem: etree._Element, path: list[str]
    ) -> str:
        """沿嵌套路径查找文本，例如 ["A", "B", "C"] → A/B/C 的文本。"""
        cur = elem
        for tag in path:
            child = cur.find(f"ns:{tag}", _NSMAP)
            if child is None:
                return ""
            cur = child
        return cur.text.strip() if cur.text else ""

    @staticmethod
    # 递归向上遍历父节点，收集每一层的 SHORT-NAME，拼接成 AUTOSAR 标准全局对象路径
    def _resolve_ref_path(elem: etree._Element) -> str:
        parts = []
        cur = elem
        while cur is not None:
            name = cur.findtext("ns:SHORT-NAME", namespaces=_NSMAP)
            if name:
                parts.append(name)
            cur = cur.getparent()
        return "/" + "/".join(reversed(parts))
