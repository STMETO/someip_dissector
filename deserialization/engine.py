"""
反序列化引擎 — 将 ARXML 类型知识与 pcap 二进制 payload 结合，产出解析树。

依赖两个上游产出：
1. TypeFactory.build_all() → type_pool (``dict[str, DataType]``)
2. ServiceRegistry.build() → registry (O(1) 查表)

输入一条 MessageDict，输出一棵 FieldNode 解析树。
"""

from __future__ import annotations

from typing import Any

from arxml_parsers.data_types import DataType
from deserialization.field_node import FieldNode
from utils.logger import get_logger

logger = get_logger(__name__)

# SOME/IP message_type → 消息方向
_REQUEST_TYPES = {0x00, 0x01}       # REQUEST / REQUEST_NO_RETURN
_RESPONSE_TYPES = {0x80}             # RESPONSE
_ERROR_TYPES = {0x81}                # ERROR
_NOTIFICATION_TYPES = {0x02}         # NOTIFICATION（事件）


class DeserializationEngine:
    """反序列化引擎。

    用法::

        engine = DeserializationEngine(type_pool, registry)
        tree = engine.deserialize_message(msg)
        print(json.dumps(tree.to_dict(), indent=2))
    """

    def __init__(
        self,
        type_pool: dict[str, DataType],
        registry: Any,  # ServiceRegistry
    ) -> None:
        self._pool = type_pool
        self._registry = registry

    # ---- 公开接口 ----

    def deserialize_message(self, msg: dict[str, Any]) -> FieldNode | None:
        """对一条 pcap 解析出来的 MessageDict 做反序列化。

        Returns
        -------
        FieldNode | None
            解析树根节点；查找失败或类型缺失返回 None。
        """
        header = msg.get("header", {})
        srv_id = header.get("service_id", {}).get("dec", 0)
        method_id = header.get("method_id", {}).get("dec", 0)
        msg_type = header.get("message_type", {}).get("dec", 0)

        # 1. 确定消息方向
        direction = self._msg_type_to_direction(msg_type)

        # 2. 查注册表 → 类型路径
        if direction == "notification":
            type_path = self._registry.lookup_event(srv_id, method_id)
        else:
            type_path = self._registry.lookup_method(srv_id, method_id, direction)

        if type_path is None:
            logger.debug("Registry miss: srv=0x%X method=%d dir=%s",
                         srv_id, method_id, direction)
            return None

        # 3. 查类型池 → DataType
        dt = self._pool.get(type_path)
        if dt is None:
            logger.debug("Type pool miss: %s", type_path)
            return None

        # 4. 反序列化
        payload_hex = msg.get("payload_hex", "")
        payload = bytes.fromhex(payload_hex)

        try:
            return dt.deserialize(payload, offset=0, name=type_path)
        except Exception:
            logger.debug("Deserialize failed for %s (payload %d bytes)",
                         type_path, len(payload), exc_info=True)
            return None

    # ---- 内部 ----

    @staticmethod
    def _msg_type_to_direction(msg_type: int) -> str:
        if msg_type in _REQUEST_TYPES:
            return "request"
        if msg_type in _RESPONSE_TYPES:
            return "response"
        if msg_type in _ERROR_TYPES:
            return "error"
        if msg_type in _NOTIFICATION_TYPES:
            return "notification"
        return "request"  # 兜底
