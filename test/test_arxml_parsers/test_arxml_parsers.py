from __future__ import annotations

import json
import sys
from pathlib import Path

# 确保项目根目录可导入
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from utils.logger import setup_logging, get_logger
from arxml_parsers import ArxmlParser, TypeFactory, ServiceRegistry

logger = get_logger(__name__)

BASE = Path(__file__).resolve().parent
ARXML_PATH = BASE / "sample.arxml"
OUTPUT_PATH = BASE / "test_output.json"

# ═══════════════════════════════════════════════════════════════
# 日志配置
# ═══════════════════════════════════════════════════════════════
LOG_CONFIG = dict(level="INFO")
# LOG_CONFIG = dict(level="DEBUG", log_dir=BASE / "logs")


def main() -> int:
    setup_logging(**LOG_CONFIG)

    logger.info("=" * 50)
    logger.info("ARXML parser test started")
    logger.info("Input:  %s", ARXML_PATH)
    logger.info("Output: %s", OUTPUT_PATH)
    logger.info("=" * 50)

    # ---- 1. Parse ----
    parser = ArxmlParser(ARXML_PATH)
    parser.parse()
    logger.info("Parsed: %d base types, %d impl types, %d interfaces, %d deployments",
                len(parser.raw_base_types), len(parser.raw_types),
                len(parser.raw_interfaces), len(parser.raw_deployments))

    # ---- 2. Build types ----
    factory = TypeFactory()
    types = factory.build_all(parser.raw_base_types, parser.raw_types)
    logger.info("Built %d DataType objects", len(types))

    # ---- 3. Build registry ----
    registry = ServiceRegistry()
    registry.build(parser.raw_deployments, parser.raw_interfaces)
    logger.info("Registry: %d methods, %d events",
                registry.method_count, registry.event_count)

    # ---- 4. Output JSON ----
    output = {
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
            for path, dt in sorted(types.items())
        },
        "registry": {
            "method_map": {str(k): v for k, v in registry._method_map.items()},
            "event_map": {str(k): v for k, v in registry._event_map.items()},
        },
    }

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info("Done. Output: %s", OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
