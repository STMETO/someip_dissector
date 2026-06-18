"""
SOME/IP Dissector — 全链路入口。

从 sample.pcap + sample.arxml 出发，依次执行：
1. PCAP 解析 → 内存中的报文列表
2. ARXML 解析 → 类型池 + 注册表
3. 反序列化 → 每条报文产出一棵 FieldNode 解析树

数据流全程走内存；中间 JSON 通过 SAVE_INTERMEDIATE 开关控制。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.logger import setup_logging, get_logger
from pcap_parsers.parser import SomeIpPcapParser, write_result_json
from pcap_parsers.strategies import UdpSomeIpStrategy, TcpSomeIpStrategy
from arxml_parsers import ArxmlParser, TypeFactory, ServiceRegistry
from arxml_parsers.exporter import export_arxml_report
from deserialization import DeserializationEngine

logger = get_logger(__name__)

# ═══════════════════════════════════════════════════════════════════
# 输入文件
# ═══════════════════════════════════════════════════════════════════

BASE = Path(__file__).resolve().parent
PCAP_IN = BASE / "sample.pcap"
ARXML_IN = BASE / "sample.arxml"

# ═══════════════════════════════════════════════════════════════════
# 输出目录（时间戳子目录）
# ═══════════════════════════════════════════════════════════════════

_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_DIR = BASE / "output" / _TIMESTAMP
LOG_DIR = BASE / "logs" / _TIMESTAMP

# 是否落盘中间产物（pcap_output.json / arxml_output.json）
# SAVE_INTERMEDIATE = True
SAVE_INTERMEDIATE = False

# ═══════════════════════════════════════════════════════════════════
# 日志配置
# ═══════════════════════════════════════════════════════════════════

LOG_CONFIG = dict(level="INFO", log_dir=LOG_DIR)
# LOG_CONFIG = dict(level="DEBUG", log_dir=LOG_DIR)   # 排查时启用

# ═══════════════════════════════════════════════════════════════════


def step1_parse_pcap() -> dict[str, Any]:
    """PCAP 解析 → 返回内存中的 ParseResultDict。"""
    logger.info("=" * 60)
    logger.info("Step 1/3: PCAP parsing — %s", PCAP_IN)

    output_path = OUTPUT_DIR / "pcap_output.json" if SAVE_INTERMEDIATE else None
    parser = SomeIpPcapParser([UdpSomeIpStrategy(), TcpSomeIpStrategy()])
    result = parser.parse(PCAP_IN, output_path or Path("/dev/null"))

    if SAVE_INTERMEDIATE and output_path:
        write_result_json(result, output_path)
        logger.info("  Saved: %s", output_path)

    logger.info("  Frames: %d | Messages: %d (UDP: %d, TCP: %d) | Errors: %d",
                result["summary"]["total_frames"],
                result["summary"]["parsed_messages"],
                result["summary"]["parsed_by_transport"]["UDP"],
                result["summary"]["parsed_by_transport"]["TCP"],
                result["summary"]["error_count"])
    return result


def step2_parse_arxml() -> tuple[dict[str, Any], ServiceRegistry]:
    """ARXML 编译 → 返回 (type_pool, registry)。"""
    logger.info("=" * 60)
    logger.info("Step 2/3: ARXML parsing — %s", ARXML_IN)

    parser = ArxmlParser(ARXML_IN)
    parser.parse()
    type_pool = TypeFactory().build_all(parser.raw_base_types, parser.raw_types)
    registry = ServiceRegistry()
    registry.build(parser.raw_deployments, parser.raw_interfaces)

    if SAVE_INTERMEDIATE:
        arxml_json = OUTPUT_DIR / "arxml_output.json"
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


def step3_deserialize(
    messages: list[dict[str, Any]],
    type_pool: dict[str, Any],
    registry: ServiceRegistry,
) -> None:
    """反序列化 → 输出 FieldNode JSON。"""
    logger.info("=" * 60)
    logger.info("Step 3/3: Deserialization — %d messages", len(messages))

    output_path = OUTPUT_DIR / "deserialized_output.json"
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


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    setup_logging(**LOG_CONFIG)

    logger.info("╔══════════════════════════════════════════════════════╗")
    logger.info("║        SOME/IP Dissector — Full Pipeline             ║")
    logger.info("╠══════════════════════════════════════════════════════╣")
    logger.info("║  PCAP:      %-40s ║", PCAP_IN.name)
    logger.info("║  ARXML:     %-40s ║", ARXML_IN.name)
    logger.info("║  Output:    %-40s ║", str(OUTPUT_DIR))
    logger.info("║  Logs:      %-40s ║", str(LOG_DIR))
    logger.info("║  Save JSON: %-40s ║", str(SAVE_INTERMEDIATE).lower())
    logger.info("╚══════════════════════════════════════════════════════╝")

    # 全程内存传递
    pcap_result = step1_parse_pcap()
    if not pcap_result["messages"]:
        logger.warning("No messages parsed — stopping.")
        return 1

    type_pool, registry = step2_parse_arxml()
    if not type_pool:
        logger.warning("No types built — stopping.")
        return 1

    step3_deserialize(pcap_result["messages"], type_pool, registry)

    logger.info("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
