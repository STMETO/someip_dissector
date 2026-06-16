from __future__ import annotations

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from utils.logger import setup_logging, get_logger
from pcap_parsers import parse_someip_pcap, write_result_json

logger = get_logger(__name__)

# ═══════════════════════════════════════════════════════════════
# 日志配置 — 按需切换
# ═══════════════════════════════════════════════════════════════

# 仅控制台 INFO
LOG_CONFIG = dict(level="INFO")

# 控制台 + 文件 DEBUG（开启下行，注释上行）
# LOG_CONFIG = dict(level="DEBUG", log_dir=Path(__file__).resolve().parent / "logs")

# ═══════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent
PCAP_PATH = BASE_DIR / "sample.pcap"
OUTPUT_PATH = BASE_DIR / "sample.json"


def main() -> int:
    setup_logging(**LOG_CONFIG)

    logger.info("=" * 50)
    logger.info("SOME/IP pcap parser started")
    logger.info("Pcap: %s", PCAP_PATH)
    logger.info("Output: %s", OUTPUT_PATH)
    logger.info("=" * 50)

    result = parse_someip_pcap(PCAP_PATH, OUTPUT_PATH)
    write_result_json(result, OUTPUT_PATH)

    logger.info("Parsed messages: %d (UDP: %d, TCP: %d), Errors: %d",
                result["summary"]["parsed_messages"],
                result["summary"]["parsed_by_transport"]["UDP"],
                result["summary"]["parsed_by_transport"]["TCP"],
                result["summary"]["error_count"])

    if result["errors"] and not result["messages"]:
        logger.warning("All frames failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
