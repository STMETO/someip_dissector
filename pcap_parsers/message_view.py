"""
PCAP 消息原始数据展示树构建。

将 pcap parser 输出的 MessageDict 中已有的结构化数据
（header / sd / payload_hex）组织成 FieldNode 树，供前端展示。
不做二次解析 — 所有数据均来自 pcap parser 的预解析结果。
"""
from __future__ import annotations
from typing import Any

from deserialization.field_node import FieldNode

# ---- SOME/IP 头部固定布局（字段名, 标签, 偏移, 字节数） ----
_HEADER_LAYOUT: list[tuple[str, str, int, int]] = [
    ("service_id",       "Service ID",        0,  2),
    ("method_id",        "Method ID",         2,  2),
    ("length",           "Length",            4,  4),
    ("client_id",        "Client ID",         8,  2),
    ("session_id",       "Session ID",       10,  2),
    ("protocol_version", "Protocol Version", 12,  1),
    ("interface_version","Interface Version",13,  1),
    ("message_type",     "Message Type",     14,  1),
    ("return_code",      "Return Code",      15,  1),
]

# ---- SD Entry/Option 中需要展示的字段 ----
_SD_ENTRY_KEYS = (
    "type", "service_id", "instance_id",
    "major_version", "ttl", "minor_version", "eventgroup_id",
)
_SD_OPTION_KEYS = (
    "type", "address", "port", "l4_proto", "priority", "weight",
)


def build_message_raw_view(msg: dict[str, Any]) -> FieldNode:
    """基于 pcap parser 已有的结构化数据构建展示树。

    所有数据来自 msg dict — 不做二次解析。
    """
    header = msg.get("header", {})
    payload_hex = msg.get("payload_hex", "")
    payload_len = len(bytes.fromhex(payload_hex)) if payload_hex else 0
    raw_header_hex = msg.get("raw_header_hex", "")
    children: list[FieldNode] = []

    # ==== Header ====
    children.append(_build_header_section(header, raw_header_hex))

    # ==== SD（数据来自 parser._parse_sd_payload）====
    sd = msg.get("sd")
    if isinstance(sd, dict):
        children.append(_build_sd_section(sd, payload_len))

    # ==== Payload ====
    if payload_hex:
        payload_bytes = bytes.fromhex(payload_hex)
        children.append(FieldNode.leaf(
            name="Payload (hex)", type_name="raw",
            value=payload_hex, offset=16, raw=payload_bytes))

    # ==== Transport ====
    children.append(FieldNode.leaf(
        name="Transport", type_name="string",
        value=_fmt_endpoint(msg), offset=0, raw=b""))

    return FieldNode.container(
        name="Raw PCAP View", type_name="raw_view",
        offset=0, byte_size=16 + payload_len,
        children=children, meta_kind="raw",
    )


# ---------------------------------------------------------------------------
# 内部构建函数
# ---------------------------------------------------------------------------

def _build_header_section(header: dict, raw_header_hex: str) -> FieldNode:
    """按 SOME/IP 固定布局切 raw_header_hex，填充偏移/字节数/原始 hex。"""
    kids: list[FieldNode] = []
    raw = bytes.fromhex(raw_header_hex) if raw_header_hex else b""
    for key, label, off, size in _HEADER_LAYOUT:
        val = header.get(key)
        field_bytes = raw[off:off + size] if len(raw) >= off + size else b""
        kids.append(FieldNode.leaf(
            name=label, type_name="hex",
            value=val.get("hex", "") if isinstance(val, dict) else str(val),
            offset=off, raw=field_bytes))
    return FieldNode.container(
        name="Header", type_name="SOME/IP Header",
        offset=0, byte_size=16, children=kids)


def _build_sd_section(sd: dict, payload_len: int) -> FieldNode:
    """构建 SD 段：Flags + Entries[] + Options[]。"""
    kids: list[FieldNode] = []

    # Flags
    flags = sd.get("flags", {})
    if flags:
        kids.append(FieldNode.container(
            name="Flags", type_name="SD_Flags", offset=0, byte_size=1,
            children=[
                FieldNode.leaf(name="raw", type_name="uint8",
                               value=flags.get("dec", 0), offset=0,
                               raw=bytes([flags.get("dec", 0) & 0xFF])),
                FieldNode.leaf(name="names", type_name="string",
                               value=", ".join(flags.get("names", ["None"])),
                               offset=0, raw=b""),
            ]))

    # Entries
    for i, entry in enumerate(sd.get("entries", [])):
        e_kids: list[FieldNode] = []
        for k in _SD_ENTRY_KEYS:
            v = entry.get(k)
            if v is None:
                continue
            if isinstance(v, dict) and "dec" in v:
                e_kids.append(FieldNode.leaf(
                    name=k, type_name="uint32", value=v["dec"],
                    offset=0, raw=b""))
            else:
                e_kids.append(FieldNode.leaf(
                    name=k, type_name="string", value=str(v),
                    offset=0, raw=b""))
        kids.append(FieldNode.container(
            name=f"Entry[{i}]", type_name=entry.get("type", "?"),
            offset=0, byte_size=0, children=e_kids))

    # Options
    for i, opt in enumerate(sd.get("options", [])):
        o_kids: list[FieldNode] = []
        for k in _SD_OPTION_KEYS:
            v = opt.get(k)
            if v is None:
                continue
            if isinstance(v, dict) and "dec" in v:
                o_kids.append(FieldNode.leaf(
                    name=k, type_name="uint32", value=v["dec"],
                    offset=0, raw=b""))
            elif isinstance(v, int):
                o_kids.append(FieldNode.leaf(
                    name=k, type_name="uint32", value=v,
                    offset=0, raw=b""))
            else:
                o_kids.append(FieldNode.leaf(
                    name=k, type_name="string", value=str(v),
                    offset=0, raw=b""))
        kids.append(FieldNode.container(
            name=f"Option[{i}]", type_name=opt.get("type", "?"),
            offset=0, byte_size=0, children=o_kids))

    return FieldNode.container(
        name="SD", type_name="Service Discovery",
        offset=16, byte_size=payload_len, children=kids)


def _fmt_endpoint(msg: dict) -> str:
    transport = msg.get("transport", "?")
    src = f"{msg.get('src_ip', '?')}:{msg.get('src_port', '?')}"
    dst = f"{msg.get('dst_ip', '?')}:{msg.get('dst_port', '?')}"
    return f"{transport}  {src} → {dst}"
