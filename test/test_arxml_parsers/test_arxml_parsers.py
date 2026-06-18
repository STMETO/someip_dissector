from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from utils.logger import setup_logging, get_logger
from arxml_parsers import ArxmlParser, TypeFactory, ServiceRegistry, export_arxml_report

logger = get_logger(__name__)

BASE = Path(__file__).resolve().parent
ARXML_PATH = BASE / "sample.arxml"
OUTPUT_PATH = BASE / "test_output.json"

LOG_CONFIG = dict(level="INFO")
# LOG_CONFIG = dict(level="DEBUG", log_dir=BASE / "logs")


def main() -> int:
    setup_logging(**LOG_CONFIG)

    logger.info("=" * 50)
    logger.info("ARXML parser test started")
    logger.info("Input:  %s", ARXML_PATH)
    logger.info("Output: %s", OUTPUT_PATH)

    parser = ArxmlParser(ARXML_PATH)
    parser.parse()
    type_pool = TypeFactory().build_all(parser.raw_base_types, parser.raw_types)
    registry = ServiceRegistry()
    registry.build(parser.raw_deployments, parser.raw_interfaces)

    export_arxml_report(
        OUTPUT_PATH,
        raw_base_types=parser.raw_base_types,
        raw_types=parser.raw_types,
        raw_interfaces=parser.raw_interfaces,
        raw_deployments=parser.raw_deployments,
        type_pool=type_pool,
        registry=registry,
    )

    logger.info("Done. Base types: %d, Types: %d, Registry: %d methods / %d events",
                len(parser.raw_base_types), len(type_pool),
                registry.method_count, registry.event_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
