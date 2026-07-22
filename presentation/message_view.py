"""
PCAP 消息原始数据展示树构建。

将 pcap parser 输出的 MessageDict 中已有的结构化数据
（header / sd / payload_hex）组织成 FieldNode 树，供前端展示。
字段值来自 pcap parser 的预解析结果；展示层只按标准布局切原始
bytes，用于补齐 offset / byte_size / raw hex。
"""
from __future__ import annotations
from typing import Any

from deserialization.field_node import FieldNode
from pcap_parsers.common import message_type_label

# ---- SOME/IP Return Code 枚举 ----
_RETURN_CODE_LABELS: dict[int, str] = {
    0x00: "E_OK",
    0x01: "E_NOT_OK",
    0x02: "E_WRONG_INTERFACE_VERSION",
    0x03: "E_WRONG_MESSAGE_TYPE",
    0x04: "E_WRONG_PROTOCOL_VERSION",
}


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
    "type", "index_first_options", "index_second_options", "number_of_options",
    "service_id", "instance_id",
    "major_version", "ttl", "minor_version", "eventgroup_id",
)
_SD_OPTION_KEYS = (
    "type", "address", "l4_proto", "port", "priority", "weight",
)

_SOMEIP_HEADER_SIZE = 16
_SD_ENTRY_SIZE = 16
_SD_ENTRY_FIELDS: dict[str, tuple[int, int]] = {
    "type": (0, 1),
    "index_first_options": (1, 1),
    "index_second_options": (2, 1),
    "number_of_options": (3, 1),
    "service_id": (4, 2),
    "instance_id": (6, 2),
    "major_version": (8, 1),
    "ttl": (9, 3),
    "minor_version": (12, 4),
    "eventgroup_id": (14, 2),
}
_SD_IPV4_OPTION_FIELDS: dict[str, tuple[int, int]] = {
    "type": (2, 1),
    "address": (4, 4),
    "l4_proto": (9, 1),
    "port": (10, 2),
}


def build_message_raw_view(msg: dict[str, Any]) -> FieldNode:
    """基于 pcap parser 已有的结构化数据构建展示树。

    字段值来自 msg dict；raw bytes 仅用于展示真实 offset/length。
    """
    header = msg.get("header", {})
    payload_hex = msg.get("payload_hex", "")
    payload_len = len(bytes.fromhex(payload_hex)) if payload_hex else 0
    raw_header_hex = msg.get("raw_header_hex", "")
    children: list[FieldNode] = []
    sd_kind = _resolve_sd_kind(msg)

    # ==== Header ====
    children.append(_build_header_section(header, raw_header_hex, sd_kind))

    # ==== SD（数据来自 parser._parse_sd_payload）====
    sd = msg.get("sd")
    if isinstance(sd, dict):
        children.append(_build_sd_section(sd, payload_len, payload_hex))

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

def _build_header_section(
    header: dict,
    raw_header_hex: str,
    sd_kind: str = "",
) -> FieldNode:
    """按 SOME/IP 固定布局切 raw_header_hex，给前端结构化展示值。"""
    kids: list[FieldNode] = []
    raw = bytes.fromhex(raw_header_hex) if raw_header_hex else b""
    for key, label, off, size in _HEADER_LAYOUT:
        val = header.get(key)
        field_bytes = raw[off:off + size] if len(raw) >= off + size else b""
        hex_str = val.get("hex", "") if isinstance(val, dict) else str(val)
        dec_val = _parse_dec_value(val, hex_str)
        meaning = _header_field_meaning(key, dec_val, sd_kind)
        display: dict[str, Any] = {
            "hex": hex_str,
            "dec": dec_val,
        }
        if meaning:
            display["meaning"] = meaning

        kids.append(FieldNode.leaf(
            name=label, type_name="hex",
            value=display, offset=off, raw=field_bytes))
    return FieldNode.container(
        name="Header", type_name="SOME/IP Header",
        offset=0, byte_size=16, children=kids)


def _parse_dec_value(val: Any, hex_str: str) -> int:
    if isinstance(val, dict) and isinstance(val.get("dec"), int):
        return val["dec"]
    if isinstance(hex_str, str) and hex_str.startswith("0x"):
        try:
            return int(hex_str, 16)
        except ValueError:
            return 0
    return 0


def _header_field_meaning(key: str, dec_val: int, sd_kind: str = "") -> str:
    if key == "message_type":
        if sd_kind:
            return f"SD {sd_kind}"
        enum = message_type_label(dec_val)
        return "" if enum.startswith("0x") else enum
    if key == "return_code":
        return _RETURN_CODE_LABELS.get(dec_val, "")
    return ""


def _resolve_sd_kind(msg: dict[str, Any]) -> str:
    header = msg.get("header", {})
    srv_id = header.get("service_id", {}).get("dec", 0)
    if srv_id != 0xFFFF:
        return ""

    labels: list[str] = []
    seen: set[str] = set()
    for entry in msg.get("sd", {}).get("entries", []):
        label = _sd_entry_kind_label(entry.get("type", ""))
        if label and label not in seen:
            labels.append(label)
            seen.add(label)
    return "/".join(labels)


def _sd_entry_kind_label(entry_type: str) -> str:
    if entry_type in {"OfferService", "StopOfferService"}:
        return "Offer"
    if entry_type == "SubscribeEventGroup":
        return "Subscribe"
    if entry_type in {
        "SubscribeEventGroupAck",
        "SubscribeEventgroupAck",
        "SubscribeEventGroupNack",
    }:
        return "SubscribeAck"
    return entry_type or ""


def _build_sd_section(sd: dict, payload_len: int, payload_hex: str) -> FieldNode:
    """Build SD tree with byte-accurate offsets inside the SOME/IP message.

    SOME/IP-SD payload layout starts immediately after the 16-byte SOME/IP
    header:

    - byte 0: flags
    - byte 1..3: reserved
    - byte 4..7: entries array length
    - byte 8..: entries, each entry is exactly 16 bytes
    - after entries: 4-byte options array length, then options
    """
    kids: list[FieldNode] = []
    payload = _safe_fromhex(payload_hex)

    # Flags
    flags = sd.get("flags", {})
    if flags:
        flags_offset = _SOMEIP_HEADER_SIZE
        flags_raw = payload[0:1] if payload else bytes([flags.get("dec", 0) & 0xFF])
        kids.append(FieldNode.container(
            name="Flags", type_name="SD_Flags",
            offset=flags_offset, byte_size=1,
            children=[
                FieldNode.leaf(name="raw", type_name="uint8",
                               value=_hex_dec_value(flags, flags_raw),
                               offset=flags_offset, raw=flags_raw),
                FieldNode.leaf(name="names", type_name="string",
                               value=", ".join(flags.get("names", ["None"])),
                               offset=flags_offset, raw=flags_raw),
            ]))

    if len(payload) >= 4:
        reserved_raw = payload[1:4]
        kids.append(FieldNode.leaf(
            name="Reserved", type_name="reserved",
            value=_hex_dec_value({"dec": int.from_bytes(reserved_raw, "big"),
                                  "hex": f"0x{int.from_bytes(reserved_raw, 'big'):06X}"},
                                 reserved_raw),
            offset=_SOMEIP_HEADER_SIZE + 1, raw=reserved_raw))

    entries_len = _read_u32(payload, 4)
    if len(payload) >= 8:
        kids.append(FieldNode.leaf(
            name="Entries Length", type_name="uint32",
            value=_hex_dec_value({"dec": entries_len,
                                  "hex": f"0x{entries_len:08X}"},
                                 payload[4:8]),
            offset=_SOMEIP_HEADER_SIZE + 4, raw=payload[4:8]))

    # Entries
    for i, entry in enumerate(sd.get("entries", [])):
        entry_payload_offset = 8 + i * _SD_ENTRY_SIZE
        entry_msg_offset = _SOMEIP_HEADER_SIZE + entry_payload_offset
        entry_raw = payload[entry_payload_offset:entry_payload_offset + _SD_ENTRY_SIZE]
        e_kids = _build_sd_entry_fields(entry, entry_msg_offset, entry_raw)
        kids.append(FieldNode.container(
            name=f"Entry[{i}]", type_name=entry.get("type", "?"),
            offset=entry_msg_offset, byte_size=len(entry_raw), children=e_kids))

    options_len_offset = 8 + entries_len
    options_len = _read_u32(payload, options_len_offset)
    if len(payload) >= options_len_offset + 4:
        kids.append(FieldNode.leaf(
            name="Options Length", type_name="uint32",
            value=_hex_dec_value({"dec": options_len,
                                  "hex": f"0x{options_len:08X}"},
                                 payload[options_len_offset:options_len_offset + 4]),
            offset=_SOMEIP_HEADER_SIZE + options_len_offset,
            raw=payload[options_len_offset:options_len_offset + 4]))

    # Options
    option_payload_offset = options_len_offset + 4
    for i, opt in enumerate(sd.get("options", [])):
        opt_raw, option_size = _slice_sd_option(payload, option_payload_offset)
        opt_msg_offset = _SOMEIP_HEADER_SIZE + option_payload_offset
        o_kids = _build_sd_option_fields(opt, opt_msg_offset, opt_raw)
        kids.append(FieldNode.container(
            name=f"Option[{i}]", type_name=opt.get("type", "?"),
            offset=opt_msg_offset, byte_size=len(opt_raw), children=o_kids))
        option_payload_offset += option_size

    return FieldNode.container(
        name="SD", type_name="Service Discovery",
        offset=_SOMEIP_HEADER_SIZE, byte_size=payload_len, children=kids)


def _build_sd_entry_fields(
    entry: dict[str, Any],
    entry_msg_offset: int,
    entry_raw: bytes,
) -> list[FieldNode]:
    children: list[FieldNode] = []
    for key in _SD_ENTRY_KEYS:
        rel_off, size = _SD_ENTRY_FIELDS[key]
        raw = entry_raw[rel_off:rel_off + size]
        value = _sd_entry_display_value(key, entry, raw)
        if value is None:
            continue
        offset = entry_msg_offset + rel_off
        children.append(_sd_leaf(key, value, offset, raw))
    return children


def _sd_entry_display_value(
    key: str,
    entry: dict[str, Any],
    raw: bytes,
) -> Any | None:
    """Return parsed display value for SD Entry fields.

    Scapy exposes service_id/ttl/etc. but does not expose every byte in the
    option-run area.  Those bytes are still protocol fields, so the presentation
    layer derives them directly from raw Entry bytes.
    """
    if key in entry:
        return entry[key]
    if key == "index_first_options" and raw:
        return {"dec": raw[0], "hex": f"0x{raw[0]:02X}"}
    if key == "index_second_options" and raw:
        return {"dec": raw[0], "hex": f"0x{raw[0]:02X}"}
    if key == "number_of_options" and raw:
        first_count = (raw[0] >> 4) & 0x0F
        second_count = raw[0] & 0x0F
        return {
            "dec": raw[0],
            "hex": f"0x{raw[0]:02X}",
            "meaning": f"first_run={first_count}, second_run={second_count}",
        }
    return None


def _build_sd_option_fields(
    opt: dict[str, Any],
    opt_msg_offset: int,
    opt_raw: bytes,
) -> list[FieldNode]:
    children: list[FieldNode] = []
    for key in _SD_OPTION_KEYS:
        value = opt.get(key)
        if value is None:
            continue
        rel_off, size = _SD_IPV4_OPTION_FIELDS.get(key, (0, 0))
        raw = opt_raw[rel_off:rel_off + size] if size else b""
        offset = opt_msg_offset + rel_off if size else opt_msg_offset
        children.append(_sd_leaf(key, value, offset, raw))
    return children


def _sd_leaf(name: str, value: Any, offset: int, raw: bytes) -> FieldNode:
    if isinstance(value, dict) and "dec" in value:
        return FieldNode.leaf(
            name=name, type_name=_uint_type_name(raw),
            value=_hex_dec_value(value, raw, value.get("meaning", "")),
            offset=offset, raw=raw)
    if isinstance(value, int):
        return FieldNode.leaf(
            name=name, type_name=_uint_type_name(raw),
            value=_hex_dec_value({"dec": value, "hex": f"0x{value:X}"}, raw),
            offset=offset, raw=raw)
    if name == "type" and raw:
        return FieldNode.leaf(
            name=name, type_name="enum",
            value=_hex_dec_value({"dec": raw[0], "hex": f"0x{raw[0]:02X}"},
                                 raw, str(value)),
            offset=offset, raw=raw)
    if name == "l4_proto" and raw:
        return FieldNode.leaf(
            name=name, type_name="enum",
            value=_hex_dec_value({"dec": raw[0], "hex": f"0x{raw[0]:02X}"},
                                 raw, str(value)),
            offset=offset, raw=raw)
    return FieldNode.leaf(
        name=name, type_name="string", value=str(value),
        offset=offset, raw=raw)


def _hex_dec_value(value: dict[str, Any], raw: bytes, meaning: str = "") -> dict[str, Any]:
    dec = int(value.get("dec", 0))
    display = {
        "hex": value.get("hex") or (f"0x{int.from_bytes(raw, 'big'):X}" if raw else f"0x{dec:X}"),
        "dec": dec,
    }
    if meaning:
        display["meaning"] = meaning
    return display


def _uint_type_name(raw: bytes) -> str:
    return f"uint{len(raw) * 8}" if raw else "uint"


def _safe_fromhex(hex_str: str) -> bytes:
    try:
        return bytes.fromhex(hex_str) if hex_str else b""
    except ValueError:
        return b""


def _read_u32(payload: bytes, offset: int) -> int:
    if len(payload) < offset + 4:
        return 0
    return int.from_bytes(payload[offset:offset + 4], "big")


def _slice_sd_option(payload: bytes, option_payload_offset: int) -> tuple[bytes, int]:
    if len(payload) < option_payload_offset + 3:
        return b"", 0
    option_len = int.from_bytes(
        payload[option_payload_offset:option_payload_offset + 2], "big")
    total_size = min(option_len + 3, len(payload) - option_payload_offset)
    return payload[option_payload_offset:option_payload_offset + total_size], total_size


def _fmt_endpoint(msg: dict) -> str:
    transport = msg.get("transport", "?")
    src = f"{msg.get('src_ip', '?')}:{msg.get('src_port', '?')}"
    dst = f"{msg.get('dst_ip', '?')}:{msg.get('dst_port', '?')}"
    return f"{transport}  {src} → {dst}"
