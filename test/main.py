#!/usr/bin/env python3
"""
SOME/IP Dissector — 命令行调试入口（全链路批处理）。

用法：
    python test/main.py [选项]

    python test/main.py --pcap sample.pcap --arxml sample.arxml
    python test/main.py --pcap my.pcap --arxml my.arxml --log-level DEBUG --save-json
    python test/main.py --help

测试文件存放位置：
    PCAP  : 项目根目录下 sample.pcap（或通过 --pcap 指定）
    ARXML : 项目根目录下 sample.arxml（或通过 --arxml 指定）
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# 确保项目根目录在 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from utils.logger import setup_logging, get_logger
from pcap_parsers.parser import SomeIpPcapParser, write_result_json
from pcap_parsers.strategies import UdpSomeIpStrategy, TcpSomeIpStrategy
from arxml_parsers import ArxmlParser, TypeFactory, ServiceRegistry
from arxml_parsers.exporter import export_arxml_report
from deserialization import DeserializationEngine

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="SOME/IP Dissector — 命令行全链路解析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python test/main.py
    python test/main.py --pcap my.pcap --arxml my.arxml --log-level DEBUG
    python test/main.py --save-json --log-level INFO

测试文件默认位置（项目根目录）:
    sample.pcap     PCAP 抓包文件
    sample.arxml    AUTOSAR ARXML 服务定义文件
""",
    )
    p.add_argument("--pcap", default=str(_PROJECT_ROOT / "test" / "test_deserialization" / "sample.pcap"),
                   help="PCAP 文件路径（默认: test/test_deserialization/sample.pcap）")
    p.add_argument("--arxml", default=str(_PROJECT_ROOT / "test" / "test_deserialization" / "sample.arxml"),
                   help="ARXML 文件路径（默认: test/test_deserialization/sample.arxml）")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                   help="日志输出等级（默认: INFO）")
    p.add_argument("--output", default=None,
                   help="结果输出目录（默认: output/<时间戳>）")
    p.add_argument("--log-dir", default=None,
                   help="日志文件目录（默认: logs/<时间戳>）")
    p.add_argument("--save-json", action="store_true", default=True,
                   help="保存中间 JSON 文件（默认: 开启）")
    return p


# ═══════════════════════════════════════════════════════════════════
# Pipeline
# ═══════════════════════════════════════════════════════════════════

def parse_pcap(pcap_path: Path, output_dir: Path,
                     save_json: bool) -> dict[str, Any]:
    logger.info("=" * 60)
    logger.info("Step 1/3: PCAP parsing — %s", pcap_path)

    out = output_dir / "pcap_output.json" if save_json else None
    parser = SomeIpPcapParser([UdpSomeIpStrategy(), TcpSomeIpStrategy()])
    result = parser.parse(pcap_path, out or Path("/dev/null"))

    if save_json and out:
        write_result_json(result, out)
        logger.info("  Saved: %s", out)

    logger.info("  Frames: %d | Messages: %d (UDP: %d, TCP: %d) | Errors: %d",
                result["summary"]["total_frames"],
                result["summary"]["parsed_messages"],
                result["summary"]["parsed_by_transport"]["UDP"],
                result["summary"]["parsed_by_transport"]["TCP"],
                result["summary"]["error_count"])
    return result


def parse_arxml(arxml_path: Path, output_dir: Path,
                      save_json: bool) -> tuple[dict[str, Any], ServiceRegistry]:
    logger.info("=" * 60)
    logger.info("Step 2/3: ARXML parsing — %s", arxml_path)

    parser = ArxmlParser(arxml_path)
    parser.parse()
    type_pool = TypeFactory().build_all(parser.raw_base_types, parser.raw_types)
    registry = ServiceRegistry()
    registry.build(parser.raw_deployments, parser.raw_interfaces)

    if save_json:
        arxml_json = output_dir / "arxml_output.json"
        export_arxml_report(
            arxml_json,
            raw_base_types=parser.raw_base_types,
            raw_types=parser.raw_types,
            raw_interfaces=parser.raw_interfaces,
            raw_deployments=parser.raw_deployments,
            type_pool=type_pool,
            registry=registry,
        )
        logger.info("  Saved: %s", arxml_json)

    logger.info("  Base types: %d | Impl types: %d | Interfaces: %d | Deployments: %d",
                len(parser.raw_base_types), len(parser.raw_types),
                len(parser.raw_interfaces), len(parser.raw_deployments))
    logger.info("  Type pool: %d | Registry: %d methods / %d events",
                len(type_pool), registry.method_count, registry.event_count)
    return type_pool, registry


def deserialize(messages: list[dict[str, Any]],
                      type_pool: dict[str, Any],
                      registry: ServiceRegistry,
                      output_dir: Path) -> None:
    logger.info("=" * 60)
    logger.info("Step 3/3: Deserialization — %d messages", len(messages))

    output_path = output_dir / "deserialized_output.json"
    engine = DeserializationEngine(type_pool, registry)

    results: list[dict[str, Any]] = []
    hit = 0
    for msg in messages:
        tree = engine.deserialize_message(msg)
        if tree is not None:
            results.append({
                "index": msg["index"],
                "frame_index": msg["frame_index"],
                "transport": msg["transport"],
                "service_id": msg["header"]["service_id"]["hex"],
                "method_id": msg["header"]["method_id"]["hex"],
                "message_type": msg["header"]["message_type"]["hex"],
                "tree": tree.to_dict(),
            })
            hit += 1

    output = {
        "summary": {
            "total_messages": len(messages),
            "deserialized": hit,
            "missed": len(messages) - hit,
        },
        "results": results,
    }
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info("  Deserialized: %d / %d (%.1f%%) → %s",
                hit, len(messages),
                100 * hit / len(messages) if messages else 0,
                output_path)


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    pcap_path = Path(args.pcap)
    arxml_path = Path(args.arxml)

    if not pcap_path.exists():
        logger.error("PCAP file not found: %s", pcap_path)
        return 1
    if not arxml_path.exists():
        logger.error("ARXML file not found: %s", arxml_path)
        return 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output) if args.output else _PROJECT_ROOT / "output" / ts
    log_dir = Path(args.log_dir) if args.log_dir else _PROJECT_ROOT / "logs" / ts

    output_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(level=args.log_level, log_dir=log_dir)

    logger.info("╔══════════════════════════════════════════════════════╗")
    logger.info("║                   SOME/IP Dissector                  ║")
    logger.info("╠══════════════════════════════════════════════════════╣")
    logger.info("║  PCAP:      %-40s ║", pcap_path.name)
    logger.info("║  ARXML:     %-40s ║", arxml_path.name)
    logger.info("║  Output:    %-40s ║", str(output_dir))
    logger.info("║  Logs:      %-40s ║", str(log_dir))
    logger.info("║  Log Level: %-40s ║", args.log_level)
    logger.info("║  Save JSON: %-40s ║", str(args.save_json).lower())
    logger.info("╚══════════════════════════════════════════════════════╝")

    pcap_result = parse_pcap(pcap_path, output_dir, args.save_json)
    if not pcap_result["messages"]:
        logger.warning("No messages parsed — stopping.")
        return 1

    type_pool, registry = parse_arxml(arxml_path, output_dir, args.save_json)
    if not type_pool:
        logger.warning("No types built — stopping.")
        return 1

    deserialize(pcap_result["messages"], type_pool, registry, output_dir)

    logger.info("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
