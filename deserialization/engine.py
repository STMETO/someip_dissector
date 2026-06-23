"""
反序列化引擎 — 将 ARXML 类型知识与 pcap 二进制 payload 结合，产出解析树。

输入：单条 pcap 报文字典 MessageDict
输出：FieldNode 解析树；无法解析返回 None
"""
from __future__ import annotations
from typing import Any

from datatypes.types import DataType
from deserialization.field_node import FieldNode
from pcap_parsers.common import (
    EVENT_ID_MASK,
    SOMEIP_SD_SERVICE_ID,
    get_msg_direction,
)
from utils.logger import get_logger

logger = get_logger(__name__)

_SD_SERVICE_ID = SOMEIP_SD_SERVICE_ID
_EVENT_ID_MASK = EVENT_ID_MASK


class DeserializationEngine:
    """顶层反序列化引擎。"""

    def __init__(self, type_pool: dict[str, DataType], registry: Any) -> None:
        self._pool = type_pool
        self._registry = registry

    def deserialize_message(self, msg: dict[str, Any]) -> FieldNode | None:
        """单条 SOME/IP 报文反序列化。SD / 查表失败 / 解析异常返回 None。"""
        header = msg.get("header", {})
        srv_id = header.get("service_id", {}).get("dec", 0)
        method_id = header.get("method_id", {}).get("dec", 0)
        msg_type = header.get("message_type", {}).get("dec", 0)

        # SD 报文不参与反序列化
        if srv_id == _SD_SERVICE_ID:
            return None

        direction = self._msg_type_to_direction(msg_type)

        # 查表
        type_path = self._resolve_type_path(srv_id, method_id, direction)
        if type_path is None:
            logger.debug("Registry miss: srv=0x%X method=%d dir=%s",
                         srv_id, method_id, direction)
            return None

        # 类型池
        dt = self._pool.get(type_path)
        if dt is None:
            logger.debug("Type pool miss: %s", type_path)
            return None

        # 反序列化
        try:
            payload = bytes.fromhex(msg.get("payload_hex", ""))
            tree, _consumed = dt.deserialize(payload, offset=0, name=type_path)
            return tree
        except Exception:
            logger.debug("Deserialize failed for %s (payload %d bytes)",
                         type_path, len(msg.get("payload_hex", "")) // 2,
                         exc_info=True)
            return None

    def _resolve_type_path(self, srv_id: int, method_id: int,
                           direction: str) -> str | None:
        if direction == "notification":
            path = self._registry.lookup_event(srv_id, method_id)
            if path is not None:
                return path
            return self._registry.lookup_event(srv_id, method_id & _EVENT_ID_MASK)
        return self._registry.lookup_method(srv_id, method_id, direction)

    @staticmethod
    def _msg_type_to_direction(msg_type: int) -> str:
        return get_msg_direction(msg_type)
