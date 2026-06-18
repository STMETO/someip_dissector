"""
deserialization 模块测试。

输入：
    sample.arxml       → 构建类型池 + 注册表
    pcap_output.json   → 消息列表（含 service_id / method_id / payload_hex）

输出：
    deserialized.json  → 每条消息的解析树

运行：cd deserialization && python test_deserialization.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 确保项目根目录可导入
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from utils.logger import setup_logging, get_logger
from arxml_parsers import ArxmlParser, TypeFactory, ServiceRegistry
from deserialization import DeserializationEngine

logger = get_logger(__name__)

BASE = Path(__file__).resolve().parent
ARXML_IN = BASE / "sample.arxml"
PCAP_OUT = BASE / "pcap_output.json"
RESULT_OUT = BASE / "deserialized.json"

LOG_CONFIG = dict(level="INFO")
# LOG_CONFIG = dict(level="DEBUG", log_dir=BASE / "logs")


def load_pcap_messages(path: Path) -> list[dict]:
    with path.open("r") as f:
        data = json.load(f)
    return data["messages"]


def main() -> int:
    setup_logging(**LOG_CONFIG)

    logger.info("=" * 50)
    logger.info("Deserialization test started")

    # ---- 1. 构建类型知识库 ----
    logger.info("Parsing ARXML: %s", ARXML_IN)
    parser = ArxmlParser(ARXML_IN)
    parser.parse()
    type_pool = TypeFactory().build_all(parser.raw_base_types, parser.raw_types)
    registry = ServiceRegistry()
    registry.build(parser.raw_deployments, parser.raw_interfaces)
    logger.info("Types: %d, Registry: %d methods / %d events",
                len(type_pool), registry.method_count, registry.event_count)

    # ---- 2. 创建引擎 ----
    engine = DeserializationEngine(type_pool, registry)

    # ---- 3. 加载 pcap 消息 ----
    messages = load_pcap_messages(PCAP_OUT)
    logger.info("Loaded %d messages from %s", len(messages), PCAP_OUT)

    # ---- 4. 逐条反序列化 ----
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

    # ---- 5. 输出 ----
    output = {
        "summary": {
            "total_messages": len(messages),
            "deserialized": hit,
            "missed": len(messages) - hit,
        },
        "results": results,
    }
    with RESULT_OUT.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info("Deserialized: %d / %d (hit rate: %.1f%%)",
                hit, len(messages),
                100 * hit / len(messages) if messages else 0)
    logger.info("Output: %s", RESULT_OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
