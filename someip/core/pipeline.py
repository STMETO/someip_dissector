"""Full SOME/IP parsing pipeline.

This module is the boundary between low-level parsers and callers such as the
Web API or CLI tools.  It owns the ordered workflow:

1. Compile ARXML into a type pool and service registry.
2. Parse PCAP into normalized SOME/IP message dictionaries.
3. Deserialize payloads with the compiled ARXML knowledge.

The module intentionally returns plain Python data structures because the rest
of the project already uses dictionaries for parsed messages.  The important
part is that Web/session code no longer directly constructs parser objects.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from someip.arxml_parsers import ArxmlParser, ServiceRegistry, TypeFactory
from someip.arxml_parsers.exporter import export_arxml_report
from someip.deserialization import DeserializationEngine
from someip.pcap_parsers.common import SOMEIP_SD_SERVICE_ID
from someip.pcap_parsers.parser import SomeIpPcapParser
from someip.pcap_parsers.strategies import TcpSomeIpStrategy, UdpSomeIpStrategy
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ParsePipelineResult:
    """All outputs produced by one full parse run.

    ``messages`` are internal enriched messages.  They include payload
    deserialization results and ``parse_status``, but they do not include
    frontend-only trees such as ``raw_view``.
    """

    pcap_result: dict[str, Any]
    arxml_parser: ArxmlParser
    type_pool: dict[str, Any]
    registry: ServiceRegistry
    messages: list[dict[str, Any]]
    parsed_count: int
    timings: dict[str, float]

    @property
    def total_messages(self) -> int:
        return len(self.messages)


def run_parse_pipeline(pcap_path: Path, arxml_path: Path) -> ParsePipelineResult:
    """Run ARXML compilation, PCAP parsing, and payload deserialization."""
    timings: dict[str, float] = {}
    total_start = time.perf_counter()

    started = time.perf_counter()
    arxml_parser, type_pool, registry = _compile_arxml(arxml_path)
    timings["arxml_compile_ms"] = _elapsed_ms(started)

    started = time.perf_counter()
    pcap_result = _parse_pcap(pcap_path)
    timings["pcap_parse_ms"] = _elapsed_ms(started)

    started = time.perf_counter()
    messages, parsed_count = _deserialize_messages(
        pcap_result["messages"], type_pool, registry)
    timings["payload_deserialize_ms"] = _elapsed_ms(started)
    timings["pipeline_total_ms"] = _elapsed_ms(total_start)

    logger.info(
        "Pipeline timings | arxml=%.1fms pcap=%.1fms deserialize=%.1fms total=%.1fms messages=%d parsed=%d",
        timings["arxml_compile_ms"],
        timings["pcap_parse_ms"],
        timings["payload_deserialize_ms"],
        timings["pipeline_total_ms"],
        len(messages),
        parsed_count,
    )

    return ParsePipelineResult(
        pcap_result=pcap_result,
        arxml_parser=arxml_parser,
        type_pool=type_pool,
        registry=registry,
        messages=messages,
        parsed_count=parsed_count,
        timings=timings,
    )


def save_pipeline_exports(
    session_dir: Path,
    result: ParsePipelineResult,
    presentation_messages: list[dict[str, Any]] | None = None,
) -> dict[str, float]:
    """Save debug/export JSON files for a parse run.

    ``presentation_messages`` is optional on purpose: the core pipeline can be
    used without the Web UI, but when Web rendering is available we persist the
    same message shape that the frontend consumes.
    """
    timings: dict[str, float] = {}
    total_start = time.perf_counter()
    export_dir = session_dir / "export"
    export_dir.mkdir(exist_ok=True)

    started = time.perf_counter()
    with (export_dir / "pcap_output.json").open("w", encoding="utf-8") as f:
        json.dump(result.pcap_result, f, ensure_ascii=False, indent=2)
    timings["export_pcap_json_ms"] = _elapsed_ms(started)

    started = time.perf_counter()
    export_arxml_report(
        export_dir / "arxml_output.json",
        raw_base_types=result.arxml_parser.raw_base_types,
        raw_types=result.arxml_parser.raw_types,
        raw_interfaces=result.arxml_parser.raw_interfaces,
        raw_deployments=result.arxml_parser.raw_deployments,
        type_pool=result.type_pool,
        registry=result.registry,
    )
    timings["export_arxml_json_ms"] = _elapsed_ms(started)

    started = time.perf_counter()
    exported_messages = presentation_messages or result.messages
    with (export_dir / "deserialized_output.json").open("w", encoding="utf-8") as f:
        json.dump({
            "summary": {
                "total_messages": len(exported_messages),
                "parsed_count": result.parsed_count,
            },
            "messages": exported_messages,
        }, f, ensure_ascii=False, indent=2)
    timings["export_deserialized_json_ms"] = _elapsed_ms(started)
    timings["export_total_ms"] = _elapsed_ms(total_start)

    logger.info(
        "Export timings | pcap_json=%.1fms arxml_json=%.1fms deserialized_json=%.1fms total=%.1fms",
        timings["export_pcap_json_ms"],
        timings["export_arxml_json_ms"],
        timings["export_deserialized_json_ms"],
        timings["export_total_ms"],
    )
    return timings


def _compile_arxml(arxml_path: Path) -> tuple[ArxmlParser, dict[str, Any], ServiceRegistry]:
    """Compile ARXML into executable type and service lookup objects."""
    arxml_parser = ArxmlParser(arxml_path)
    arxml_parser.parse()

    type_pool = TypeFactory().build_all(
        arxml_parser.raw_base_types,
        arxml_parser.raw_types,
    )

    registry = ServiceRegistry()
    registry.build(arxml_parser.raw_deployments, arxml_parser.raw_interfaces)
    return arxml_parser, type_pool, registry


def _parse_pcap(pcap_path: Path) -> dict[str, Any]:
    """Parse PCAP using transport strategies, including TCP stream handling."""
    pcap_parser = SomeIpPcapParser([UdpSomeIpStrategy(), TcpSomeIpStrategy()])
    return pcap_parser.parse(pcap_path, Path("/dev/null"))


def _deserialize_messages(
    raw_messages: list[dict[str, Any]],
    type_pool: dict[str, Any],
    registry: ServiceRegistry,
) -> tuple[list[dict[str, Any]], int]:
    """Attach payload parse trees and parse status to raw SOME/IP messages."""
    engine = DeserializationEngine(type_pool, registry)
    messages: list[dict[str, Any]] = []
    parsed_count = 0

    for raw_msg in raw_messages:
        # Copy each message so the PCAP parser output remains a stable artifact.
        msg = dict(raw_msg)
        srv_id = msg["header"]["service_id"]["dec"]

        if srv_id == SOMEIP_SD_SERVICE_ID:
            msg["parse_status"] = "sd"
        else:
            tree = engine.deserialize_message(msg)
            if tree is not None:
                msg["parsed"] = tree.to_dict()
                msg["parse_status"] = "ok"
            else:
                msg["parse_status"] = "unresolved"

        if _is_resolved_status(msg["parse_status"]):
            parsed_count += 1
        messages.append(msg)

    return messages, parsed_count


def _is_resolved_status(status: str) -> bool:
    """Statuses other than ``unresolved`` are useful frontend parse hits."""
    return status != "unresolved"


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)
