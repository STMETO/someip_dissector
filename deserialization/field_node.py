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
        :param name: 字段名
        :param type_name: 类型名称
        :param value: 解析后的数字/字符串值
        :param offset: 二进制起始偏移
        :param raw: 当前字段原始二进制字节
        :return: 叶子FieldNode，带value、hex，无children
        """
        return cls(
            name=name,
            type_name=type_name,
            value=value,
            offset=offset,
            # 字节长度 = 原始二进制字节长度
            byte_size=len(raw),
            # 原始bytes转16进制，报文调试查看原始数据
            hex=raw.hex(),
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
        :param name: 结构体/数组名称
        :param type_name: 结构体/数组类型名
        :param offset: 该复合结构在payload中的起始偏移
        :param byte_size: 整个结构体/数组总占用字节
        :param children: 内部所有子字段/数组元素节点列表
        :return: 容器FieldNode，value=None，hex为空，携带children子树
        """
        return cls(
            name=name,
            type_name=type_name,
            value=None,
            offset=offset,
            byte_size=byte_size,
            hex="",  # 复合结构不存整体hex，子节点各自携带自身原始hex
            children=children,
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
        # 存在子节点，递归转换所有子节点字典放入children数组
        if self.children:
            node_dict["children"] = [child.to_dict() for child in self.children]
        return node_dict
