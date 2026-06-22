"""全链路解析管道 — 串联 PCAP → ARXML → 反序列化。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from pcap_parsers.parser import SomeIpPcapParser
from pcap_parsers.strategies import TcpSomeIpStrategy, UdpSomeIpStrategy
from arxml_parsers import ArxmlParser, TypeFactory, ServiceRegistry
from arxml_parsers.exporter import export_arxml_report
from deserialization import DeserializationEngine
from deserialization.field_node import FieldNode
from web.backend.handlers.upload import cleanup_session, validate_and_save


@dataclass
class _SessionState:
    session_id: str
    session_dir: Path
    messages: list[dict[str, Any]]
    total_messages: int = 0
    parsed_count: int = 0
    keep_temp: bool = False


_sessions: dict[str, _SessionState] = {}

# SOME/IP-SD Service ID
_SD_SERVICE_ID = 0xFFFF

# ---- 头字段布局（字段名, 标签, 偏移, 字节数） ----
_HEADER_FIELDS: list[tuple[str, str, int, int]] = [
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


async def run_upload_and_parse(
    pcap_file: UploadFile,
    arxml_file: UploadFile,
    keep_temp: bool = False,
) -> dict[str, Any]:
    """上传并执行全链路解析。"""
    pcap_path, arxml_path, session_id = await validate_and_save(
        pcap_file, arxml_file, keep_temp)
    session_dir = pcap_path.parent

    # 1. ARXML
    arxml_parser = ArxmlParser(arxml_path)
    arxml_parser.parse()
    type_pool = TypeFactory().build_all(arxml_parser.raw_base_types,
                                        arxml_parser.raw_types)
    registry = ServiceRegistry()
    registry.build(arxml_parser.raw_deployments, arxml_parser.raw_interfaces)

    # 2. PCAP
    pcap_parser = SomeIpPcapParser([UdpSomeIpStrategy(), TcpSomeIpStrategy()])
    pcap_result = pcap_parser.parse(pcap_path, Path("/dev/null"))

    # 保存中间 JSON
    if keep_temp:
        export_dir = session_dir / "export"
        export_dir.mkdir(exist_ok=True)
        with (export_dir / "pcap_output.json").open("w", encoding="utf-8") as f:
            json.dump(pcap_result, f, ensure_ascii=False, indent=2)
        export_arxml_report(
            export_dir / "arxml_output.json",
            raw_base_types=arxml_parser.raw_base_types,
            raw_types=arxml_parser.raw_types,
            raw_interfaces=arxml_parser.raw_interfaces,
            raw_deployments=arxml_parser.raw_deployments,
            type_pool=type_pool,
            registry=registry,
        )

    # 3. 反序列化
    engine = DeserializationEngine(type_pool, registry)
    messages: list[dict[str, Any]] = []
    parsed_count = 0
    for raw_msg in pcap_result["messages"]:
        msg = dict(raw_msg)
        srv_id = msg["header"]["service_id"]["dec"]

        # 确定解析状态
        if srv_id == _SD_SERVICE_ID:
            msg["parse_status"] = "sd"
        else:
            tree = engine.deserialize_message(msg)
            if tree is not None:
                msg["parsed"] = tree.to_dict()
                msg["parse_status"] = "ok"
                parsed_count += 1
            else:
                msg["parse_status"] = "unresolved"

        # 每条消息都构建原始 pcap 数据视图
        msg["raw_view"] = _build_raw_view(msg).to_dict()
        msg["message_kind"] = _label(msg["header"]["message_type"]["dec"])
        messages.append(msg)

    if keep_temp:
        export_dir = session_dir / "export"
        with (export_dir / "deserialized_output.json").open("w", encoding="utf-8") as f:
            json.dump({
                "summary": {
                    "total_messages": len(messages),
                    "parsed_count": parsed_count,
                },
                "messages": messages,
            }, f, ensure_ascii=False, indent=2)

    state = _SessionState(
        session_id=session_id, session_dir=session_dir,
        messages=messages, total_messages=len(messages),
        parsed_count=parsed_count, keep_temp=keep_temp,
    )
    _sessions[session_id] = state

    if not keep_temp:
        cleanup_session(session_id)

    return {
        "session_id": session_id,
        "summary": {
            "total_messages": state.total_messages,
            "parsed_count": state.parsed_count,
        },
        "has_export": keep_temp,
    }


# ---------------------------------------------------------------------------
# 原始 pcap 数据视图构建
# ---------------------------------------------------------------------------

def _build_raw_view(msg: dict[str, Any]) -> FieldNode:
    """基于 pcap parser 已有的结构化数据构建展示树。

    所有数据都来自 msg dict（header / sd / payload_hex），
    不做二次解析，直接组织成树供前端展示。
    """
    header = msg.get("header", {})
    payload_hex = msg.get("payload_hex", "")
    payload_len = len(bytes.fromhex(payload_hex)) if payload_hex else 0
    raw_header_hex = msg.get("raw_header_hex", "")
    children: list[FieldNode] = []

    # ---- Header 段（按固定布局切 raw_header_hex 填充偏移/字节数/原始hex） ----
    header_kids: list[FieldNode] = []
    raw_hdr_bytes = bytes.fromhex(raw_header_hex) if raw_header_hex else b""
    for key, label, off, size in _HEADER_FIELDS:
        val = header.get(key)
        field_bytes = raw_hdr_bytes[off:off + size] if len(raw_hdr_bytes) >= off + size else b""
        header_kids.append(FieldNode.leaf(
            name=label, type_name="hex",
            value=val.get("hex", "") if isinstance(val, dict) else str(val),
            offset=off, raw=field_bytes))
    children.append(FieldNode.container(
        name="Header", type_name="SOME/IP Header",
        offset=0, byte_size=16, children=header_kids))

    # ---- SD 段（数据来自 pcap parser 的 _parse_sd_payload） ----
    sd = msg.get("sd")
    if isinstance(sd, dict):
        sd_kids: list[FieldNode] = []

        # Flags
        flags = sd.get("flags", {})
        if flags:
            f_kids: list[FieldNode] = [
                FieldNode.leaf(name="raw", type_name="uint8",
                               value=flags.get("dec", 0), offset=0,
                               raw=bytes([flags.get("dec", 0) & 0xFF])),
                FieldNode.leaf(name="names", type_name="string",
                               value=", ".join(flags.get("names", ["None"])),
                               offset=0, raw=b""),
            ]
            sd_kids.append(FieldNode.container(
                name="Flags", type_name="SD_Flags",
                offset=0, byte_size=1, children=f_kids))

        # Entries
        for i, entry in enumerate(sd.get("entries", [])):
            e_kids: list[FieldNode] = []
            for k in ("type", "service_id", "instance_id",
                      "major_version", "ttl", "minor_version",
                      "eventgroup_id"):
                v = entry.get(k)
                if v is None:
                    continue
                if isinstance(v, dict) and "dec" in v:
                    e_kids.append(FieldNode.leaf(
                        name=k, type_name="uint32",
                        value=v["dec"], offset=0, raw=b""))
                else:
                    e_kids.append(FieldNode.leaf(
                        name=k, type_name="string",
                        value=str(v), offset=0, raw=b""))
            sd_kids.append(FieldNode.container(
                name=f"Entry[{i}]", type_name=entry.get("type", "?"),
                offset=0, byte_size=0, children=e_kids))

        # Options
        for i, opt in enumerate(sd.get("options", [])):
            o_kids: list[FieldNode] = []
            for k in ("type", "address", "port", "l4_proto",
                      "priority", "weight"):
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
            sd_kids.append(FieldNode.container(
                name=f"Option[{i}]", type_name=opt.get("type", "?"),
                offset=0, byte_size=0, children=o_kids))

        children.append(FieldNode.container(
            name="SD", type_name="Service Discovery",
            offset=16, byte_size=payload_len, children=sd_kids))

    # ---- Payload 段 ----
    if payload_hex:
        payload_bytes = bytes.fromhex(payload_hex)
        children.append(FieldNode.leaf(
            name="Payload (hex)", type_name="raw",
            value=payload_hex, offset=16, raw=payload_bytes))

    # ---- 传输信息 ----
    children.append(FieldNode.leaf(
        name="Transport", type_name="string",
        value=f"{msg.get('transport', '?')}  {msg.get('src_ip', '?')}:{msg.get('src_port', '?')} → {msg.get('dst_ip', '?')}:{msg.get('dst_port', '?')}",
        offset=0, raw=b""))

    return FieldNode.container(
        name="Raw PCAP View",
        type_name="raw_view",
        offset=0,
        byte_size=16 + payload_len,
        children=children,
        meta_kind="raw",
    )


# ---------------------------------------------------------------------------
# 会话 / 导出 / 摘要
# ---------------------------------------------------------------------------

def get_session(session_id: str) -> _SessionState | None:
    return _sessions.get(session_id)


def clear_session(session_id: str) -> None:
    state = _sessions.pop(session_id, None)
    if state:
        cleanup_session(session_id)


def get_export_path(session_id: str, filename: str) -> Path | None:
    state = _sessions.get(session_id)
    if not state or not state.keep_temp:
        return None
    p = state.session_dir / "export" / filename
    return p if p.is_file() else None


def build_message_summaries(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "index": m["index"],
            "frame_index": m["frame_index"],
            "service_id": m["header"]["service_id"]["hex"],
            "method_id": m["header"]["method_id"]["hex"],
            "message_type": m["header"]["message_type"]["hex"],
            "message_kind": m.get("message_kind", "?"),
            "transport": m["transport"],
            "payload_length": m["payload_length"],
            "parse_status": m.get("parse_status", "unresolved"),
        }
        for m in messages
    ]


def build_message_detail(messages: list[dict[str, Any]], index: int) -> dict | None:
    for m in messages:
        if m["index"] == index:
            return {
                "index": m["index"],
                "frame_index": m["frame_index"],
                "service_id": m["header"]["service_id"]["hex"],
                "method_id": m["header"]["method_id"]["hex"],
                "message_type": m["header"]["message_type"]["hex"],
                "message_kind": m.get("message_kind", "?"),
                "transport": m["transport"],
                "payload_length": m["payload_length"],
                "payload_hex": m["payload_hex"],
                "raw_header_hex": m["raw_header_hex"],
                "parse_status": m.get("parse_status", "unresolved"),
                "parsed": m.get("parsed"),
                "raw_view": m.get("raw_view"),
            }


def _label(message_type: int) -> str:
    if message_type in {0x00, 0x01}:
        return "Request"
    if message_type == 0x02:
        return "Notification"
    if message_type == 0x80:
        return "Response"
    if message_type == 0x81:
        return "Error"
    return f"0x{message_type:02X}"
