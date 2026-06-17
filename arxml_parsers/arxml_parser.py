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

_AR_NS = "http://autosar.org/schema/r4.0"
_NSMAP = {"ns": _AR_NS}


# ======================================================================
# 数据类
# ======================================================================


@dataclass
class RawBaseType:
    """SW-BASE-TYPE 原始信息。"""

    name: str
    path: str = ""
    bit_size: int = 0
    encoding: str = ""
    byte_order: str = ""   # OPAQUE | BIG-ENDIAN | LITTLE-ENDIAN


@dataclass
class RawDataType:
    """一个 STD-CPP-IMPLEMENTATION-DATA-TYPE 的原始信息。"""

    name: str
    path: str = ""
    category: str = ""          # TYPE_REFERENCE | VALUE | STRUCTURE | VECTOR | ARRAY
    type_ref: str = ""           # TYPE-REFERENCE-REF 或 TEMPLATE-TYPE-REF
    array_size: int = 0          # VECTOR / ARRAY
    sub_elements: list[RawSubElement] = field(default_factory=list)


@dataclass
class RawSubElement:
    """STRUCTURE / CPP-IMPLEMENTATION-DATA-TYPE-ELEMENT 中的一个字段。"""

    name: str
    type_ref: str


@dataclass
class RawMethodArg:
    """ARGUMENT-DATA-PROTOTYPE 的原始信息。"""

    name: str
    type_ref: str
    direction: str = ""  # IN | OUT | INOUT


@dataclass
class RawServiceMethod:
    """一个 CLIENT-SERVER-OPERATION 的参数信息。"""

    name: str
    arguments: list[RawMethodArg] = field(default_factory=list)


@dataclass
class RawServiceEvent:
    """一个 VARIABLE-DATA-PROTOTYPE 的原始信息。"""

    name: str
    type_ref: str


@dataclass
class RawServiceInterface:
    """一个 SERVICE-INTERFACE 的完整信息。"""

    name: str
    path: str
    methods: dict[str, RawServiceMethod] = field(default_factory=dict)
    events: dict[str, RawServiceEvent] = field(default_factory=dict)


@dataclass
class RawMethodDeployment:
    method_id: int
    method_ref: str


@dataclass
class RawEventDeployment:
    event_id: int
    event_ref: str


@dataclass
class RawServiceDeployment:
    service_id: int
    interface_ref: str
    methods: list[RawMethodDeployment] = field(default_factory=list)
    events: list[RawEventDeployment] = field(default_factory=list)


# ======================================================================
# Parser
# ======================================================================


class ArxmlParser:
    """解析 ARXML 文件，提取原始数据。"""

    def __init__(self, filepath: str | Path):
        self.filepath = Path(filepath)
        self._root: etree._Element | None = None

        self.raw_base_types: list[RawBaseType] = []
        self.raw_types: list[RawDataType] = []
        self.raw_interfaces: list[RawServiceInterface] = []
        self.raw_deployments: list[RawServiceDeployment] = []

    # ---- 公开接口 ----

    def parse(self) -> None:
        self._load_xml()
        self.raw_base_types = self._extract_base_types()
        self.raw_types = self._extract_impl_types()
        self.raw_interfaces = self._extract_service_interfaces()
        self.raw_deployments = self._extract_deployments()

    def _load_xml(self) -> None:
        self._root = etree.parse(
            str(self.filepath), etree.XMLParser(remove_blank_text=True)
        ).getroot()

    # ==================================================================
    # BASE TYPE（SW-BASE-TYPE）
    # ==================================================================

    def _extract_base_types(self) -> list[RawBaseType]:
        elements = self._root.findall(".//ns:SW-BASE-TYPE", _NSMAP)
        result = []
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

            if category == "TYPE_REFERENCE":
                rd.type_ref = self._child_text(elem, "TYPE-REFERENCE-REF") or ""
            elif category == "STRUCTURE":
                rd.sub_elements = self._extract_struct_elements(elem)
            elif category in ("VECTOR", "ARRAY"):
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

            result.append(dep)
        return result

    # ==================================================================
    # 工具方法
    # ==================================================================

    @staticmethod
    def _child_text(elem: etree._Element, tag: str) -> str | None:
        child = elem.find(f"ns:{tag}", _NSMAP)
        return child.text.strip() if child is not None and child.text else None

    @staticmethod
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
    def _resolve_ref_path(elem: etree._Element) -> str:
        parts = []
        cur = elem
        while cur is not None:
            name = cur.findtext("ns:SHORT-NAME", namespaces=_NSMAP)
            if name:
                parts.append(name)
            cur = cur.getparent()
        return "/" + "/".join(reversed(parts))
