"""
SOME/IP Dissector — 全链路入口。

从 sample.pcap + sample.arxml 出发，依次执行：
1. PCAP 解析 → SOME/IP 报文提取 + SD 解析
2. ARXML 解析 → 类型编译 + 注册表构建
3. 反序列化 → 每条报文产出一棵 FieldNode 解析树

输出文件写入 output/<timestamp>/，日志写入 logs/<timestamp>/。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from utils.logger import setup_logging, get_logger
from pcap_parsers.parser import parse_someip_pcap, write_result_json
from arxml_parsers import ArxmlParser, TypeFactory, ServiceRegistry
from deserialization import DeserializationEngine

logger = get_logger(__name__)

# ═══════════════════════════════════════════════════════════════════
# 路径配置
# ═══════════════════════════════════════════════════════════════════

BASE = Path(__file__).resolve().parent
PCAP_IN = BASE / "sample.pcap"
ARXML_IN = BASE / "sample.arxml"

# 时间戳目录
_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_DIR = BASE / "output" / _TIMESTAMP
LOG_DIR = BASE / "logs" / _TIMESTAMP

# 输出文件
PCAP_JSON = OUTPUT_DIR / "pcap_output.json"
ARXML_JSON = OUTPUT_DIR / "arxml_output.json"
DESERIALIZED_JSON = OUTPUT_DIR / "deserialized_output.json"

# ═══════════════════════════════════════════════════════════════════
# 日志配置
# ═══════════════════════════════════════════════════════════════════

LOG_CONFIG = dict(level="INFO", log_dir=LOG_DIR)
# 排查问题时改为：
# LOG_CONFIG = dict(level="DEBUG", log_dir=LOG_DIR)

# ═══════════════════════════════════════════════════════════════════


def step1_parse_pcap() -> dict:
    """解析 PCAP，输出 JSON。"""
    logger.info("=" * 60)
    logger.info("Step 1/3: PCAP parsing")
    logger.info("  Input:  %s", PCAP_IN)
    logger.info("  Output: %s", PCAP_JSON)

    result = parse_someip_pcap(PCAP_IN, PCAP_JSON)
    write_result_json(result, PCAP_JSON)

    logger.info("  Frames: %d, Messages: %d (UDP: %d, TCP: %d), Errors: %d",
                result["summary"]["total_frames"],
                result["summary"]["parsed_messages"],
                result["summary"]["parsed_by_transport"]["UDP"],
                result["summary"]["parsed_by_transport"]["TCP"],
                result["summary"]["error_count"])
    return result


def step2_parse_arxml() -> tuple[dict, dict, ServiceRegistry]:
    """解析 ARXML，构建类型池和注册表，输出 JSON。"""
    logger.info("=" * 60)
    logger.info("Step 2/3: ARXML parsing")
    logger.info("  Input:  %s", ARXML_IN)
    logger.info("  Output: %s", ARXML_JSON)

    parser = ArxmlParser(ARXML_IN)
    parser.parse()

    type_pool = TypeFactory().build_all(parser.raw_base_types, parser.raw_types)
    registry = ServiceRegistry()
    registry.build(parser.raw_deployments, parser.raw_interfaces)

    # 输出 ARXML 编译结果
    arxml_output = {
        "base_types": [
            {"name": bt.name, "path": bt.path, "bit_size": bt.bit_size,
             "byte_order": bt.byte_order, "encoding": bt.encoding}
            for bt in parser.raw_base_types
        ],
        "types": [
            {"name": t.name, "path": t.path, "category": t.category,
             "type_ref": t.type_ref, "array_size": t.array_size,
             "sub_elements": [{"name": s.name, "type_ref": s.type_ref}
                              for s in t.sub_elements]}
            for t in parser.raw_types
        ],
        "interfaces": [
            {"name": i.name, "path": i.path,
             "methods": {
                 n: [{"name": a.name, "type_ref": a.type_ref,
                      "direction": a.direction} for a in m.arguments]
                 for n, m in i.methods.items()
             },
             "events": {n: e.type_ref for n, e in i.events.items()}}
            for i in parser.raw_interfaces
        ],
        "deployments": [
            {"service_id": d.service_id, "interface_ref": d.interface_ref,
             "method_ids": [m.method_id for m in d.methods],
             "event_ids": [e.event_id for e in d.events]}
            for d in parser.raw_deployments
        ],
        "built_types": {
            path: {"kind": type(dt).__name__, "name": dt.name,
                   "byte_size": dt.byte_size}
            for path, dt in sorted(type_pool.items())
        },
        "registry": {
            "method_map": {str(k): v for k, v in registry._method_map.items()},
            "event_map": {str(k): v for k, v in registry._event_map.items()},
        },
    }
    with ARXML_JSON.open("w", encoding="utf-8") as f:
        json.dump(arxml_output, f, ensure_ascii=False, indent=2)

    logger.info("  Base types: %d, Impl types: %d, Interfaces: %d, Deployments: %d",
                len(parser.raw_base_types), len(parser.raw_types),
                len(parser.raw_interfaces), len(parser.raw_deployments))
    logger.info("  Type pool: %d, Registry: %d methods / %d events",
                len(type_pool), registry.method_count, registry.event_count)
    return type_pool, registry


def step3_deserialize(type_pool: dict, registry: ServiceRegistry) -> None:
    """反序列化 PCAP 报文，输出 JSON。"""
    logger.info("=" * 60)
    logger.info("Step 3/3: Deserialization")
    logger.info("  Input:  %s", PCAP_JSON)
    logger.info("  Output: %s", DESERIALIZED_JSON)

    with PCAP_JSON.open("r") as f:
        messages = json.load(f)["messages"]

    engine = DeserializationEngine(type_pool, registry)

    results: list[dict] = []
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

    deserialized_output = {
        "summary": {
            "total_messages": len(messages),
            "deserialized": hit,
            "missed": len(messages) - hit,
        },
        "results": results,
    }
    with DESERIALIZED_JSON.open("w", encoding="utf-8") as f:
        json.dump(deserialized_output, f, ensure_ascii=False, indent=2)

    logger.info("  Deserialized: %d / %d (hit rate: %.1f%%)",
                hit, len(messages),
                100 * hit / len(messages) if messages else 0)


def main() -> int:
    # 创建输出目录
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # 初始化日志
    setup_logging(**LOG_CONFIG)

    logger.info("╔══════════════════════════════════════════════════════╗")
    logger.info("║                   SOME/IP Dissector                  ║")
    logger.info("╠══════════════════════════════════════════════════════╣")
    logger.info("║  PCAP:  %-44s ║", PCAP_IN.name)
    logger.info("║  ARXML: %-44s ║", ARXML_IN.name)
    logger.info("║  Output: %-43s ║", str(OUTPUT_DIR))
    logger.info("║  Logs:   %-43s ║", str(LOG_DIR))
    logger.info("╚══════════════════════════════════════════════════════╝")

    # Step 1: PCAP 解析
    pcap_result = step1_parse_pcap()
    if not pcap_result["messages"]:
        logger.warning("No messages parsed from pcap — stopping.")
        return 1

    # Step 2: ARXML 编译
    type_pool, registry = step2_parse_arxml()
    if not type_pool:
        logger.warning("No types built from ARXML — stopping.")
        return 1

    # Step 3: 反序列化
    step3_deserialize(type_pool, registry)

    logger.info("")
    logger.info("All done. Output directory: %s", OUTPUT_DIR)
    logger.info("Log directory: %s", LOG_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
