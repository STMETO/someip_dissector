"""
ARXML 原始数据提取器。

使用 lxml 解析 ARXML 文件，提取三类原始信息，**不涉及二进制解析逻辑**：

1. **数据类型原始描述** — 每个 IMPLEMENTATION-DATA-TYPE 的元素树
2. **服务接口操作 → 参数类型引用** — 方法名到 TYPE-REF 的映射
3. **SOME/IP 部署映射** — (Service ID, Method ID, Message Type) → TYPE-REF

输出给 type_factory 和 service_registry 使用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree

# AUTOSAR XML namespace
_AR_NS = "http://autosar.org/schema/r4.0"
_NSMAP = {"ns": _AR_NS}


# ---------------------------------------------------------------------------
# 提取结果的数据类
# ---------------------------------------------------------------------------


@dataclass
class RawDataType:
    """一个 IMPLEMENTATION-DATA-TYPE 的原始提取信息。"""

    name: str
    path: str = ""     # /Package/... 形式的唯一路径
    category: str = ""  # VALUE | STRUCTURE | ARRAY
    base_type_ref: str | None = None  # VALUE 类型指向 SW-BASE-TYPE
    sub_elements: list[RawSubElement] = field(default_factory=list)
    array_element: RawArrayElement | None = None


@dataclass
class RawSubElement:
    """STRUCTURE 中的一个字段。"""

    name: str
    type_ref: str


@dataclass
class RawArrayElement:
    """ARRAY 类型的元素定义。"""

    type_ref: str
    array_size: int | None = None


@dataclass
class RawServiceMethod:
    """一个 CLIENT-SERVER-OPERATION 的参数信息。"""

    name: str
    arguments: dict[str, str] = field(default_factory=dict)  # arg_name → type_ref


@dataclass
class RawServiceEvent:
    """一个事件的类型信息。"""

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
    """一个 SOMEIP-METHOD-DEPLOYMENT 的映射。"""

    method_id: int
    method_ref: str  # → CLIENT-SERVER-OPERATION 的路径


@dataclass
class RawEventDeployment:
    """一个 SOMEIP-EVENT-DEPLOYMENT 的映射。"""

    event_id: int
    event_ref: str  # → VARIABLE-DATA-PROTOTYPE 的路径


@dataclass
class RawServiceDeployment:
    """一个 SOMEIP-SERVICE-INTERFACE-DEPLOYMENT 的完整信息。"""

    service_id: int
    interface_ref: str  # → SERVICE-INTERFACE 的路径
    methods: list[RawMethodDeployment] = field(default_factory=list)
    events: list[RawEventDeployment] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class ArxmlParser:
    """解析一个 ARXML 文件，提取原始数据。

    用法::

        parser = ArxmlParser("/path/to/file.arxml")
        parser.parse()
        raw_types = parser.raw_types          # list[RawDataType]
        raw_interfaces = parser.raw_interfaces # list[RawServiceInterface]
        raw_deployments = parser.raw_deployments # list[RawServiceDeployment]
    """

    def __init__(self, filepath: str | Path):
        self.filepath = Path(filepath)
        self._tree: etree._ElementTree | None = None
        self._root: etree._Element | None = None

        # 解析结果
        self.raw_types: list[RawDataType] = []
        self.raw_interfaces: list[RawServiceInterface] = []
        self.raw_deployments: list[RawServiceDeployment] = []

    # ---- 公开接口 ----

    def parse(self) -> None:
        """执行全部提取流程。"""
        self._load_xml()
        self.raw_types = self._extract_data_types()
        self.raw_interfaces = self._extract_service_interfaces()
        self.raw_deployments = self._extract_deployments()

    # ---- XML 加载 ----

    def _load_xml(self) -> None:
        parser = etree.XMLParser(remove_blank_text=True)
        self._tree = etree.parse(str(self.filepath), parser)
        self._root = self._tree.getroot()

    # ---- 数据类型提取 ----

    def _extract_data_types(self) -> list[RawDataType]:
        elements = self._root.findall(".//ns:IMPLEMENTATION-DATA-TYPE", _NSMAP)
        result = []
        for elem in elements:
            name = self._child_text(elem, "SHORT-NAME") or ""
            category = self._child_text(elem, "CATEGORY") or ""
            path = self._resolve_ref_path(elem)
            rd = RawDataType(name=name, path=path, category=category)

            if category == "VALUE":
                rd.base_type_ref = self._extract_base_type_ref(elem)
            elif category == "STRUCTURE":
                rd.sub_elements = self._extract_sub_elements(elem)
            elif category == "ARRAY":
                rd.array_element = self._extract_array_element(elem)

            result.append(rd)
        return result

    def _extract_base_type_ref(self, elem: etree._Element) -> str | None:
        ref = elem.find(".//ns:BASE-TYPE-REF", _NSMAP)
        return ref.text.strip() if ref is not None and ref.text else None

    def _extract_sub_elements(self, elem: etree._Element) -> list[RawSubElement]:
        subs = []
        for sub in elem.findall(".//ns:IMPLEMENTATION-DATA-TYPE-ELEMENT", _NSMAP):
            name = self._child_text(sub, "SHORT-NAME") or ""
            type_ref = self._child_text(sub, "TYPE-REF") or ""
            if name and type_ref:
                subs.append(RawSubElement(name=name, type_ref=type_ref))
        return subs

    def _extract_array_element(self, elem: etree._Element) -> RawArrayElement | None:
        arr_elem = elem.find(".//ns:IMPLEMENTATION-DATA-TYPE-ELEMENT", _NSMAP)
        if arr_elem is None:
            return None
        type_ref = self._child_text(arr_elem, "TYPE-REF") or ""
        return RawArrayElement(type_ref=type_ref)

    # ---- 服务接口提取 ----

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

            # 事件 (VARIABLE-DATA-PROTOTYPE under EVENTS)
            for evt in elem.findall("./ns:EVENTS/ns:VARIABLE-DATA-PROTOTYPE", _NSMAP):
                evt_name = self._child_text(evt, "SHORT-NAME") or ""
                evt_type_ref = self._child_text(evt, "TYPE-REF") or ""
                if evt_name:
                    iface.events[evt_name] = RawServiceEvent(name=evt_name, type_ref=evt_type_ref)

            result.append(iface)
        return result

    def _extract_method(self, op_elem: etree._Element) -> RawServiceMethod:
        name = self._child_text(op_elem, "SHORT-NAME") or ""
        method = RawServiceMethod(name=name)
        for arg in op_elem.findall(".//ns:ARGUMENT-DATA-PROTOTYPE", _NSMAP):
            arg_name = self._child_text(arg, "SHORT-NAME") or ""
            arg_type_ref = self._child_text(arg, "TYPE-REF") or ""
            if arg_name and arg_type_ref:
                method.arguments[arg_name] = arg_type_ref
        return method

    # ---- SOME/IP 部署提取 ----

    def _extract_deployments(self) -> list[RawServiceDeployment]:
        elements = self._root.findall(
            ".//ns:SOMEIP-SERVICE-INTERFACE-DEPLOYMENT", _NSMAP
        )
        result = []
        for elem in elements:
            srv_id_str = self._child_text(elem, "SERVICE-ID") or "0"
            iface_ref = self._child_text(elem, "SERVICE-INTERFACE-REF") or ""

            dep = RawServiceDeployment(
                service_id=int(srv_id_str),
                interface_ref=iface_ref,
            )

            # 方法部署
            for md in elem.findall(".//ns:SOMEIP-METHOD-DEPLOYMENT", _NSMAP):
                mid_str = self._child_text(md, "METHOD-ID") or "0"
                mref = self._child_text(md, "METHOD-REF") or ""
                dep.methods.append(
                    RawMethodDeployment(method_id=int(mid_str), method_ref=mref)
                )

            # 事件部署
            for ed in elem.findall(".//ns:SOMEIP-EVENT-DEPLOYMENT", _NSMAP):
                eid_str = self._child_text(ed, "EVENT-ID") or "0"
                eref = self._child_text(ed, "EVENT-REF") or ""
                dep.events.append(
                    RawEventDeployment(event_id=int(eid_str), event_ref=eref)
                )

            result.append(dep)
        return result

    # ---- 工具方法 ----

    @staticmethod
    def _child_text(elem: etree._Element, tag: str) -> str | None:
        child = elem.find(f"ns:{tag}", _NSMAP)
        return child.text.strip() if child is not None and child.text else None

    @staticmethod
    def _resolve_ref_path(elem: etree._Element) -> str:
        """从当前元素向上遍历，构造 /Package/.../ElementName 路径。"""
        parts = []
        current = elem
        while current is not None:
            name = current.findtext("ns:SHORT-NAME", namespaces=_NSMAP)
            if name:
                parts.append(name)
            current = current.getparent()
        return "/" + "/".join(reversed(parts))
