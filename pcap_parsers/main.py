import sys
from pathlib import Path

# 确保项目根目录可导入（兼容从任意目录直接执行本文件）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from utils.logger import setup_logging, get_logger
from parser import main

logger = get_logger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# 日志配置 — 按需切换下面三组之一
# ═══════════════════════════════════════════════════════════════════════════

# ── 模式1：仅控制台，INFO 级别（日常使用） ──
# LOG_CONFIG = dict(level="INFO")

# ── 模式2：控制台 + 输出到文件（开启此行，注释模式1） ──
LOG_CONFIG = dict(level="DEBUG", log_dir=_PROJECT_ROOT / "logs")

# ── 模式3：详细排查（DEBUG + 文件，每帧/每条消息全量记录） ──
# LOG_CONFIG = dict(level="DEBUG", log_file=_PROJECT_ROOT / "logs" / "debug.log")

# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    setup_logging(**LOG_CONFIG)
    logger.info("=" * 50)
    logger.info("SOME/IP pcap parser started")
    logger.info("Log mode: level=%s, file=%s",
                LOG_CONFIG.get("level"),
                "yes" if any(k in LOG_CONFIG for k in ("log_dir", "log_file")) else "no")
    logger.info("=" * 50)
    exit_code = main()
    logger.info("Parser finished, exit code: %d", exit_code)
    raise SystemExit(exit_code)
