"""
解析结果节点 — 反序列化
纯数据容器，不包含任何二进制解析逻辑。
每个节点代表二进制 payload 中的一段数据：基础数值/字符串/结构体/数组元素
通过 children 父子关联，最终组成完整树形报文结构，用于打印、前端展示、导出JSON。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FieldNode:
    """
    二进制报文解析树通用节点
    分为两类节点：
        1. 叶子节点 leaf：基础类型uint8/int32/字符串，存储单个value，无children
        2. 容器节点 container：结构体/数组，无value，靠children存储内部子字段/数组元素

    Attributes
    ----------
    name:
        字段名称；根节点一般填消息/事件名，数组元素为 arr[0]/arr[1]
    type_name:
        数据类型短名，如 uint32_t、Struct_RouteInfo、StrVar_NMEA
    value:
        解析出的业务值；叶子节点存int/str/float；结构体/数组容器固定为None
    offset:
        当前节点在原始二进制payload中的起始字节偏移位置
    byte_size:
        当前节点自身占用总字节长度（容器节点包含所有子节点总字节）
    hex:
        当前节点原始二进制转十六进制字符串，调试报文用；容器节点为空字符串
    children:
        子节点列表：结构体存所有字段、数组存所有元素；叶子节点为空列表
    """
    name: str
    type_name: str
    value: Any = None
    offset: int = 0
    byte_size: int = 0
    hex: str = ""
    # 子节点列表，每个实例独立空列表，避免多实例共享列表bug
    children: list[FieldNode] = field(default_factory=list)
    # 内部标记，不参与序列化；to_dict() 据此输出 kind 字段
    _is_container: bool = field(default=False, repr=False)

    # ------------------------------------------------------------------
    # 工厂静态方法：快速创建两种节点，统一封装构造逻辑
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
        """
        构造叶子节点：用于 BaseType / StringType 单一数值
        """
        return cls(
            name=name,
            type_name=type_name,
            value=value,
            offset=offset,
            byte_size=len(raw),
            hex=raw.hex(),
            # _is_container 默认 False
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
        """
        构造容器节点：用于 StructureType 结构体 / ArrayType 数组
        """
        return cls(
            name=name,
            type_name=type_name,
            value=None,
            offset=offset,
            byte_size=byte_size,
            hex="",
            children=children,
            _is_container=True,
        )

    # ------------------------------------------------------------------
    # 序列化工具：转字典，支持JSON导出、前端展示
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """
        递归把当前节点+所有子节点转换成标准字典，可直接json.dumps序列化
        自动按需填充字段，精简输出，无数据的key不写入字典
        """
        # 基础固定字段
        node_dict: dict[str, Any] = {
            "name": self.name,
            "type": self.type_name,
            "offset": self.offset,
            "byte_size": self.byte_size,
        }
        # 存在原始十六进制则加入
        if self.hex:
            node_dict["hex"] = self.hex
        # 叶子节点有解析值，加入value字段
        if self.value is not None:
            node_dict["value"] = self.value
        # 根据内部标记区分容器/叶子；容器始终输出 children（即使为空数组）
        if self._is_container:
            node_dict["kind"] = "container"
            node_dict["children"] = [child.to_dict() for child in self.children]
        else:
            node_dict["kind"] = "leaf"
        return node_dict
