"""
反序列化引擎 — 将 ARXML 类型知识与 pcap 二进制 payload 结合，产出解析树。

输入：单条 pcap 报文字典 MessageDict
输出：FieldNode 解析树（永不返回 None）
"""
from __future__ import annotations
from typing import Any

from datatypes.types import DataType
from deserialization.field_node import FieldNode
from utils.logger import get_logger

logger = get_logger(__name__)

# ---- SOME/IP 报文类型常量 ----
_REQUEST_TYPES = {0x00, 0x01}
_RESPONSE_TYPES = {0x80}
_ERROR_TYPES = {0x81}
_NOTIFICATION_TYPES = {0x02}

# SOME/IP-SD 固定 Service ID
_SD_SERVICE_ID = 0xFFFF

# 事件 ID 掩码
_EVENT_ID_MASK = 0x7FFF


class DeserializationEngine:
    """顶层反序列化引擎。"""

    def __init__(self, type_pool: dict[str, DataType], registry: Any) -> None:
        self._pool = type_pool
        self._registry = registry

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------

    def deserialize_message(self, msg: dict[str, Any]) -> FieldNode:
        """单条 SOME/IP 报文完整解析。无法解析时返回含错误信息的容器节点。"""
        header = msg.get("header", {})
        srv_id = header.get("service_id", {}).get("dec", 0)
        method_id = header.get("method_id", {}).get("dec", 0)
        msg_type = header.get("message_type", {}).get("dec", 0)
        payload_hex = msg.get("payload_hex", "")

        # ---- SD 报文：构建结构化 SD 树 ----
        if srv_id == _SD_SERVICE_ID:
            return self._build_sd_tree(msg)

        direction = self._msg_type_to_direction(msg_type)

        # ---- 注册表查询 ----
        type_path = self._registry.lookup_event(srv_id, method_id) \
            if direction == "notification" else None
        if type_path is None and direction == "notification":
            type_path = self._registry.lookup_event(srv_id, method_id & _EVENT_ID_MASK)
        if type_path is None:
            type_path = self._registry.lookup_method(srv_id, method_id, direction)

        if type_path is None:
            logger.debug("Registry miss: srv=0x%X method=%d dir=%s",
                         srv_id, method_id, direction)
            return self._build_unresolved_tree(msg, f"Registry miss: no type registered for 0x{srv_id:04X}/0x{method_id:04X}")

        # ---- 类型池查找 ----
        dt = self._pool.get(type_path)
        if dt is None:
            logger.debug("Type pool miss: %s", type_path)
            return self._build_unresolved_tree(msg, f"Type pool miss: {type_path}")

        # ---- 二进制反序列化 ----
        try:
            payload = bytes.fromhex(payload_hex)
            tree, _consumed = dt.deserialize(payload, offset=0, name=type_path)
            return tree
        except Exception:
            logger.debug("Deserialize failed for %s (payload %d bytes)",
                         type_path, len(payload_hex) // 2, exc_info=True)
            return self._build_unresolved_tree(msg, f"Deserialization failed for {type_path}")

    # ------------------------------------------------------------------
    # SD 树构建
    # ------------------------------------------------------------------

    def _build_sd_tree(self, msg: dict[str, Any]) -> FieldNode:
        """基于 pcap_parsers 预解析的 SD 数据构建结构化树。"""
        sd = msg.get("sd")
        payload_hex = msg.get("payload_hex", "")
        payload_len = len(bytes.fromhex(payload_hex)) if payload_hex else 0
        children: list[FieldNode] = []

        if sd and isinstance(sd, dict):
            # -- Flags --
            flags = sd.get("flags", {})
            if flags:
                flag_kids: list[FieldNode] = []
                flag_kids.append(FieldNode.leaf(
                    name="raw", type_name="uint8",
                    value=flags.get("dec", 0), offset=0,
                    raw=bytes([flags.get("dec", 0) & 0xFF])))
                flag_kids.append(FieldNode.leaf(
                    name="names", type_name="string",
                    value=", ".join(flags.get("names", ["None"])), offset=1,
                    raw=b""))
                children.append(FieldNode.container(
                    name="Flags", type_name="SD_Flags",
                    offset=0, byte_size=1, children=flag_kids))

            # -- Entries --
            for i, entry in enumerate(sd.get("entries", [])):
                entry_kids: list[FieldNode] = []
                for key in ("type", "service_id", "instance_id",
                           "major_version", "ttl", "minor_version",
                           "eventgroup_id"):
                    val = entry.get(key)
                    if val is None:
                        continue
                    if isinstance(val, dict) and "dec" in val:
                        entry_kids.append(FieldNode.leaf(
                            name=key, type_name="uint32",
                            value=val["dec"], offset=0, raw=b""))
                    else:
                        entry_kids.append(FieldNode.leaf(
                            name=key, type_name="string",
                            value=str(val), offset=0, raw=b""))
                children.append(FieldNode.container(
                    name=f"Entry[{i}]", type_name=entry.get("type", "?"),
                    offset=0, byte_size=0, children=entry_kids))

            # -- Options --
            for i, opt in enumerate(sd.get("options", [])):
                opt_kids: list[FieldNode] = []
                for key in ("type", "address", "port", "l4_proto",
                           "priority", "weight"):
                    val = opt.get(key)
                    if val is None:
                        continue
                    if isinstance(val, dict) and "dec" in val:
                        opt_kids.append(FieldNode.leaf(
                            name=key, type_name="uint32",
                            value=val["dec"], offset=0, raw=b""))
                    elif isinstance(val, int):
                        opt_kids.append(FieldNode.leaf(
                            name=key, type_name="uint32",
                            value=val, offset=0, raw=b""))
                    else:
                        opt_kids.append(FieldNode.leaf(
                            name=key, type_name="string",
                            value=str(val), offset=0, raw=b""))
                children.append(FieldNode.container(
                    name=f"Option[{i}]", type_name=opt.get("type", "?"),
                    offset=0, byte_size=0, children=opt_kids))

        # 即使 SD 解析失败也至少显示原始 hex
        if not children:
            children.append(FieldNode.leaf(
                name="payload_raw", type_name="hex",
                value=payload_hex, offset=0,
                raw=bytes.fromhex(payload_hex) if payload_hex else b""))

        return FieldNode.container(
            name="SOME/IP-SD Service Discovery",
            type_name="SD",
            offset=0, byte_size=payload_len,
            children=children, meta_kind="sd")

    # ------------------------------------------------------------------
    # 未解析报文树构建
    # ------------------------------------------------------------------

    def _build_unresolved_tree(self, msg: dict[str, Any],
                               reason: str) -> FieldNode:
        """构建未解析报文的详情树：头部字段 + 原始 hex。"""
        header = msg.get("header", {})
        payload_hex = msg.get("payload_hex", "")
        payload_len = len(bytes.fromhex(payload_hex)) if payload_hex else 0
        children: list[FieldNode] = []

        # 头部关键字段
        for field_key, label in [
            ("service_id", "Service ID"), ("method_id", "Method ID"),
            ("message_type", "Message Type"), ("return_code", "Return Code"),
            ("length", "Length"), ("protocol_version", "Protocol Version"),
            ("interface_version", "Interface Version"),
        ]:
            val = header.get(field_key)
            if isinstance(val, dict):
                children.append(FieldNode.leaf(
                    name=label, type_name="hex",
                    value=val.get("hex", ""), offset=0, raw=b""))
            elif val is not None:
                children.append(FieldNode.leaf(
                    name=label, type_name="string",
                    value=str(val), offset=0, raw=b""))

        # 失败原因
        children.append(FieldNode.leaf(
            name="Reason", type_name="string", value=reason, offset=0, raw=b""))

        # 传输信息
        children.append(FieldNode.leaf(
            name="Transport", type_name="string",
            value=msg.get("transport", "?"), offset=0, raw=b""))

        # 原始负载 hex
        children.append(FieldNode.leaf(
            name="Payload (hex)", type_name="raw",
            value=payload_hex, offset=0,
            raw=bytes.fromhex(payload_hex) if payload_hex else b""))

        return FieldNode.container(
            name=f"Unresolved 0x{header.get('service_id', {}).get('hex', '?')}/{header.get('method_id', {}).get('hex', '?')}",
            type_name="unresolved",
            offset=0, byte_size=payload_len,
            children=children, meta_kind="unresolved")

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

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
        return "request"
