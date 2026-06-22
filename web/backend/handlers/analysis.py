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
from web.backend.handlers.upload import cleanup_session, validate_and_save


@dataclass
class _SessionState:
    """一次解析会话的完整状态。"""

    session_id: str
    session_dir: Path
    messages: list[dict[str, Any]]
    total_messages: int = 0
    parsed_count: int = 0
    keep_temp: bool = False


# 单机内存会话存储
_sessions: dict[str, _SessionState] = {}


async def run_upload_and_parse(
    pcap_file: UploadFile,
    arxml_file: UploadFile,
    keep_temp: bool = False,
) -> dict[str, Any]:
    """上传并执行全链路解析，返回 API 摘要。"""
    pcap_path, arxml_path, session_id = await validate_and_save(
        pcap_file, arxml_file, keep_temp
    )
    session_dir = pcap_path.parent

    # 1. ARXML
    parser = ArxmlParser(arxml_path)
    parser.parse()
    type_pool = TypeFactory().build_all(parser.raw_base_types, parser.raw_types)
    registry = ServiceRegistry()
    registry.build(parser.raw_deployments, parser.raw_interfaces)

    # 2. PCAP
    pcap_parser = SomeIpPcapParser([UdpSomeIpStrategy(), TcpSomeIpStrategy()])
    pcap_result = pcap_parser.parse(pcap_path, Path("/dev/null"))

    # 保存中间 JSON（需要时）
    if keep_temp:
        export_dir = session_dir / "export"
        export_dir.mkdir(exist_ok=True)
        # pcap output
        with (export_dir / "pcap_output.json").open("w", encoding="utf-8") as f:
            json.dump(pcap_result, f, ensure_ascii=False, indent=2)
        # arxml output
        export_arxml_report(
            export_dir / "arxml_output.json",
            raw_base_types=parser.raw_base_types,
            raw_types=parser.raw_types,
            raw_interfaces=parser.raw_interfaces,
            raw_deployments=parser.raw_deployments,
            type_pool=type_pool,
            registry=registry,
        )

    # 3. 反序列化
    engine = DeserializationEngine(type_pool, registry)
    messages: list[dict[str, Any]] = []
    parsed_count = 0
    for raw_msg in pcap_result["messages"]:
        msg = dict(raw_msg)
        tree = engine.deserialize_message(msg)
        if tree is not None:
            msg["parsed"] = tree.to_dict()
            msg["parse_status"] = "ok"
            parsed_count += 1
        else:
            msg["parsed"] = None
            msg["parse_status"] = "unresolved"
        msg["message_kind"] = _label(msg["header"]["message_type"]["dec"])
        messages.append(msg)

    if keep_temp:
        export_dir = session_dir / "export"
        with (export_dir / "deserialized_output.json").open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "summary": {
                        "total_messages": len(messages),
                        "parsed_count": parsed_count,
                        "unresolved_count": len(messages) - parsed_count,
                    },
                    "messages": messages,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

    state = _SessionState(
        session_id=session_id,
        session_dir=session_dir,
        messages=messages,
        total_messages=len(messages),
        parsed_count=parsed_count,
        keep_temp=keep_temp,
    )
    _sessions[session_id] = state

    # 清理上传文件
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
