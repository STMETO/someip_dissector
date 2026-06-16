"""
项目统一日志模块。

基于标准库 :mod:`logging` 封装，支持：
- 多级别输出（DEBUG / INFO / WARNING / ERROR / CRITICAL）
- 控制台彩色打印
- 文件轮转写入
- 模块级日志获取
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


#: 默认日志格式（含时间、模块、级别、消息）
DEFAULT_FMT = "%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s"
DEFAULT_DATE_FMT = "%Y-%m-%d %H:%M:%S"

#: 控制台格式（简洁版，不含时间）
CONSOLE_FMT = "%(name)-20s | %(levelname)-8s | %(message)s"


_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _resolve_level(raw: int | str) -> int:
    """将字符串级别（如 ``"DEBUG"``）转为 ``logging.DEBUG`` 整数常量。"""
    if isinstance(raw, int):
        return raw
    upper = raw.upper()
    if upper in _LEVEL_MAP:
        return _LEVEL_MAP[upper]
    raise ValueError(f"Unknown log level: {raw!r}. Valid: {list(_LEVEL_MAP)}")


class _LevelFilter(logging.Filter):
    """按日志级别过滤，将低于阈值的消息路由到 stdout，其余路由到 stderr。"""

    def __init__(self, max_level: int):
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


def setup_logging(
    level: int | str = logging.DEBUG,
    *,
    log_file: Optional[str | Path] = None,
    log_dir: Optional[str | Path] = None,
    log_name: str = "someip_dissector",
    console: bool = True,
    file_level: Optional[int | str] = None,
    console_level: Optional[int | str] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
) -> logging.Logger:
    """初始化项目根日志器（一次性配置）。

    Parameters
    ----------
    level:
        根日志器最低级别，默认 ``DEBUG``。
    log_file:
        日志文件路径。若只提供 ``log_dir``，则在目录下自动生成文件名。
    log_dir:
        日志输出目录，与 ``log_file`` 二选一；同时传入则优先 ``log_file``。
    log_name:
        根日志器名称，默认 ``"someip_dissector"``。子模块可通过
        ``get_logger(__name__)`` 继承配置。
    console:
        是否启用控制台输出，默认 ``True``。
    file_level:
        文件日志级别；未指定则与 ``level`` 一致。
    console_level:
        控制台日志级别；未指定则与 ``level`` 一致。
    max_bytes:
        单个日志文件最大字节数，超出后自动轮转（默认 10 MB）。
    backup_count:
        保留的历史日志文件数量（默认 5）。

    Returns
    -------
    logging.Logger
        配置完成的根日志器。
    """
    # --- 规范化级别 ---
    level_int = _resolve_level(level)
    file_level_int = _resolve_level(file_level) if file_level is not None else level_int
    console_level_int = _resolve_level(console_level) if console_level is not None else level_int

    # --- 解析日志文件路径 ---
    file_path: Optional[Path] = None
    if log_file:
        file_path = Path(log_file)
    elif log_dir:
        dir_path = Path(log_dir)
        dir_path.mkdir(parents=True, exist_ok=True)
        file_path = dir_path / f"{log_name}.log"

    # --- 根日志器 ---
    root = logging.getLogger(log_name)
    root.setLevel(level_int)
    root.handlers.clear()  # 幂等：重复调用不增加 handler

    # --- 控制台 handler ---
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_level_int)
        console_handler.setFormatter(logging.Formatter(CONSOLE_FMT, DEFAULT_DATE_FMT))
        # 按级别分流：WARNING 及以上 → stderr，其余 → stdout
        console_handler.addFilter(_LevelFilter(logging.INFO))
        root.addHandler(console_handler)

        # stderr handler for WARNING and above
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(max(console_level_int, logging.WARNING))
        stderr_handler.setFormatter(logging.Formatter(CONSOLE_FMT, DEFAULT_DATE_FMT))
        root.addHandler(stderr_handler)

    # --- 文件 handler ---
    if file_path:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            str(file_path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(file_level_int)
        file_handler.setFormatter(logging.Formatter(DEFAULT_FMT, DEFAULT_DATE_FMT))
        root.addHandler(file_handler)

    # 抑制第三方库的 DEBUG 噪音
    for noisy in ("scapy", "matplotlib", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return root


def get_logger(name: str | None = None) -> logging.Logger:
    """获取 ``someip_dissector`` 命名空间下的日志器。

    用法::

        from utils.logger import get_logger
        logger = get_logger(__name__)
        logger.info("解析完成")

    Parameters
    ----------
    name:
        通常传入 ``__name__``，自动挂在项目根日志器下。

    Returns
    -------
    logging.Logger
    """
    if name is None:
        return logging.getLogger("someip_dissector")
    return logging.getLogger(f"someip_dissector.{name}")


# ---------------------------------------------------------------------------
# 自测入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # ---- 1. 仅控制台，禁止第三方库噪音 ----
    print("=" * 60)
    print("1. 仅控制台输出（级别 INFO）")
    print("=" * 60)
    setup_logging(level="INFO")

    logger = get_logger("test.console")
    logger.debug("这条 DEBUG 不应出现")
    logger.info("控制台 INFO")
    logger.warning("控制台 WARNING (stderr)")
    logger.error("控制台 ERROR (stderr)")

    # ---- 2. 同时输出到文件 ----
    print()
    print("=" * 60)
    print("2. 控制台 + 文件（级别 DEBUG）")
    print("=" * 60)
    import tempfile
    from pathlib import Path

    tmpdir = Path(tempfile.gettempdir()) / "someip_logger_test"
    setup_logging(level="DEBUG", log_dir=tmpdir)

    logger2 = get_logger("test.file")
    logger2.debug("文件 DEBUG")
    logger2.info("文件 INFO")
    logger2.warning("文件 WARNING")

    log_file = tmpdir / "someip_dissector.log"
    print(f"\n日志文件: {log_file}")
    print(f"文件大小: {log_file.stat().st_size} bytes")
    print("文件内容:")
    print(log_file.read_text(encoding="utf-8"))

    # 清理
    import shutil
    shutil.rmtree(tmpdir)
    print("\n测试完成，临时文件已清理")
