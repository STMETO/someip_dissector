"""
反序列化引擎 — 将 ARXML 类型知识与 pcap 二进制 payload 结合，产出解析树。
依赖两个上游预处理产出：
1. TypeFactory.build_all() → type_pool 全局类型池 dict[str, DataType]
2. ServiceRegistry.build() → registry 服务ID/方法ID快速查表索引

输入：单条pcap抓包解析后的SOME/IP报文字典 MessageDict
输出：完整结构化FieldNode解析树；无匹配类型/解析异常返回None
"""
from __future__ import annotations
from typing import Any
# 预编译完成的DataType类型基类（基础类型/结构体/数组/字符串）
from datatypes.types import DataType
# 解析结果树形节点，叶子/容器节点统一载体
from deserialization.field_node import FieldNode
# 日志工具，打印缺失类型、解析失败调试信息
from utils.logger import get_logger

logger = get_logger(__name__)

# ==================== SOME/IP 协议报文类型常量映射 ====================
# 请求类报文：REQUEST / REQUEST_NO_RETURN
_REQUEST_TYPES = {0x00, 0x01}
# 响应报文
_RESPONSE_TYPES = {0x80}
# 错误响应报文
_ERROR_TYPES = {0x81}
# 事件通知报文（服务主动推送，无返回）
_NOTIFICATION_TYPES = {0x02}

# SOME/IP 协议规范：线上报文event_id最高位固定置1，ARXML部署ID只存低15位
# 掩码 0x7FFF = 0b0111_1111_1111_1111，用于剥离最高位
_EVENT_ID_MASK = 0x7FFF


class DeserializationEngine:
    """
    顶层反序列化引擎，统一封装整条SOME/IP报文解析全流程
    完整流程：提取报文头部ID → 判断报文类型 → 查表获取数据类型路径 → 取出类型定义 → 二进制解析生成FieldNode树

    使用示例：
        engine = DeserializationEngine(type_pool, registry)
        tree = engine.deserialize_message(msg)
        print(json.dumps(tree.to_dict(), indent=2))
    """

    def __init__(
        self,
        type_pool: dict[str, DataType],
        registry: Any,  # 传入ServiceRegistry实例，存储ID→类型路径映射
    ) -> None:
        # 全局类型池：key=AR完整类型路径，value=预编译完成的DataType对象
        self._pool = type_pool
        # SOME/IP注册表：service_id/method_id/event_id 快速查询对应数据类型路径
        self._registry = registry

    # ==================== 对外公开入口方法 ====================
    def deserialize_message(self, msg: dict[str, Any]) -> FieldNode | None:
        """
        单条SOME/IP报文完整解析入口
        :param msg: pcap解析出的报文字典，包含header头部信息、payload_hex十六进制负载
        :return: FieldNode根节点（完整解析树）；注册表无匹配/类型缺失/解析报错返回None
        """
        # 提取报文头部字典，无header则为空字典
        header = msg.get("header", {})
        # 读取头部 ServiceID 十进制数值
        srv_id = header.get("service_id", {}).get("dec", 0)
        # 读取头部 MethodID 十进制数值（事件报文此处存放event_id）
        method_id = header.get("method_id", {}).get("dec", 0)
        # 读取SOME/IP标准message_type报文类型字段
        msg_type = header.get("message_type", {}).get("dec", 0)

        # 步骤1：根据协议msg_type转换为内部标识方向 request/response/notification/error
        direction = self._msg_type_to_direction(msg_type)

        # 步骤2：根据消息类型，去注册表查询对应数据类型AR路径
        if direction == "notification":
            """
            事件报文特殊处理：
            SOME/IP协议规定：线上报文中event_id最高位固定为1，
            但ARXML部署配置只存储低15位ID，因此先直接查表；
            查不到时，用掩码剥离最高位0x8000重新查表匹配配置内ID
            """
            type_path = self._registry.lookup_event(srv_id, method_id)
            if type_path is None:
                # 剥离最高位，匹配ARXML原始部署event_id
                type_path = self._registry.lookup_event(
                    srv_id, method_id & _EVENT_ID_MASK
                )
        else:
            # RPC请求/响应/错误报文：通过service_id+method_id+方向查询类型路径
            type_path = self._registry.lookup_method(srv_id, method_id, direction)

        # 注册表无匹配ID组合，日志打印调试信息，直接返回不解析
        if type_path is None:
            logger.debug("Registry miss: srv=0x%X method=%d dir=%s",
                         srv_id, method_id, direction)
            return None

        # 步骤3：用查到的类型路径，去全局类型池获取完整DataType解析对象
        dt = self._pool.get(type_path)
        if dt is None:
            logger.debug("Type pool miss: %s", type_path)
            return None

        # 步骤4：将十六进制payload字符串转为二进制bytes
        payload_hex = msg.get("payload_hex", "")
        payload = bytes.fromhex(payload_hex)

        # 调用DataType统一deserialize接口解析二进制，捕获全部异常防止抓包程序崩溃
        try:
            # offset从0开始解析整包负载，根节点名称使用类型完整路径
            tree, _consumed = dt.deserialize(payload, offset=0, name=type_path)
            return tree
        except Exception:
            # 解析发生任何异常（报文截断、格式错误、解码失败等）仅打印调试日志，返回None
            logger.debug("Deserialize failed for %s (payload %d bytes)",
                         type_path, len(payload), exc_info=True)
            return None

    # ==================== 内部工具静态方法 ====================
    @staticmethod
    def _msg_type_to_direction(msg_type: int) -> str:
        """
        将SOME/IP协议标准message_type数值，转换为内部统一标识字符串
        :param msg_type: 报文头部message_type十进制值
        :return: request / response / error / notification
        """
        if msg_type in _REQUEST_TYPES:
            return "request"
        if msg_type in _RESPONSE_TYPES:
            return "response"
        if msg_type in _ERROR_TYPES:
            return "error"
        if msg_type in _NOTIFICATION_TYPES:
            return "notification"
        # 未知报文类型兜底，统一按request处理
        return "request"
