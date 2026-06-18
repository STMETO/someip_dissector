from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arxml_parsers import ArxmlParser, ServiceRegistry, TypeFactory
from deserialization import DeserializationEngine
from pcap_parsers.parser import SomeIpPcapParser
from pcap_parsers.strategies import TcpSomeIpStrategy, UdpSomeIpStrategy


@dataclass(slots=True)
class AnalysisArtifacts:
    messages: list[dict[str, Any]]
    pcap_summary: dict[str, Any]
    type_pool_size: int
    method_count: int
    event_count: int
    deserialized_count: int

    def to_export_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                "total_messages": len(self.messages),
                "deserialized": self.deserialized_count,
                "missed": len(self.messages) - self.deserialized_count,
                "type_pool_size": self.type_pool_size,
                "registry": {
                    "methods": self.method_count,
                    "events": self.event_count,
                },
                "pcap": self.pcap_summary,
            },
            "messages": self.messages,
        }


def build_analysis_payload(
    artifacts: AnalysisArtifacts,
    *,
    session_id: str,
    export_url: str | None,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "export_url": export_url,
        "summary": {
            "total_messages": len(artifacts.messages),
            "deserialized": artifacts.deserialized_count,
            "missed": len(artifacts.messages) - artifacts.deserialized_count,
            "type_pool_size": artifacts.type_pool_size,
            "registry": {
                "methods": artifacts.method_count,
                "events": artifacts.event_count,
            },
            "pcap": artifacts.pcap_summary,
        },
        "messages": artifacts.messages,
    }


def analyze_capture(pcap_path: Path, arxml_path: Path) -> AnalysisArtifacts:
    parser = ArxmlParser(arxml_path)
    parser.parse()

    type_pool = TypeFactory().build_all(parser.raw_base_types, parser.raw_types)
    registry = ServiceRegistry()
    registry.build(parser.raw_deployments, parser.raw_interfaces)

    pcap_parser = SomeIpPcapParser([UdpSomeIpStrategy(), TcpSomeIpStrategy()])
    pcap_result = pcap_parser.parse(pcap_path, pcap_path.with_suffix(".json"))

    engine = DeserializationEngine(type_pool, registry)
    messages: list[dict[str, Any]] = []
    deserialized_count = 0
    for raw_message in pcap_result["messages"]:
        message = dict(raw_message)
        tree = engine.deserialize_message(message)
        if tree is None:
            message["parsed"] = None
            message["parse_status"] = "unresolved"
        else:
            message["parsed"] = tree.to_dict()
            message["parse_status"] = "ok"
            deserialized_count += 1
        message["message_kind"] = _message_kind_label(
            message["header"]["message_type"]["dec"]
        )
        messages.append(message)

    return AnalysisArtifacts(
        messages=messages,
        pcap_summary=pcap_result["summary"],
        type_pool_size=len(type_pool),
        method_count=registry.method_count,
        event_count=registry.event_count,
        deserialized_count=deserialized_count,
    )


def _message_kind_label(message_type: int) -> str:
    if message_type in {0x00, 0x01}:
        return "Request"
    if message_type == 0x02:
        return "Notification"
    if message_type == 0x80:
        return "Response"
    if message_type == 0x81:
        return "Error"
    return f"0x{message_type:02X}"