#!/usr/bin/env python3
"""
SOME/IP Dissector — 启动器。

用法:
    python run.py                    # 查看帮助
    python run.py web                # 启动 Web 界面
    python run.py debug [选项]       # 命令行批处理
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent


def _ensure_project_path() -> None:
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))


def _kill_old_server() -> None:
    """跨平台杀掉旧 uvicorn 进程。"""
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmd = " ".join(proc.info.get("cmdline") or [])
                if "uvicorn" in cmd and "web.backend" in cmd:
                    print(f">>> 终止旧进程 PID={proc.info['pid']}")
                    proc.kill()
                if "web/start.py" in cmd:
                    print(f">>> 终止旧进程 PID={proc.info['pid']}")
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except ImportError:
        # 没有 psutil，尝试 pkill
        try:
            subprocess.run(["pkill", "-f", "uvicorn.*web.backend"],
                           capture_output=True)
            subprocess.run(["pkill", "-f", "web/start.py"],
                           capture_output=True)
        except FileNotFoundError:
            pass  # Windows 无 pkill，静默跳过


def cmd_web() -> int:
    """启动 Web 界面。"""
    _kill_old_server()
    print("=== 启动 Web 界面 ===")
    print("    浏览器打开 http://localhost:8000\n")
    _ensure_project_path()
    from web.start import ensure_frontend_built, start_server
    if not ensure_frontend_built():
        print("前端构建失败，仅启动 API 服务（/docs 可用）")
    start_server()
    return 0


def cmd_debug(argv: list[str]) -> int:
    """命令行批处理。"""
    debug_script = str(_PROJECT_ROOT / "test" / "main.py")
    result = subprocess.run(
        [sys.executable, debug_script] + argv,
        cwd=str(_PROJECT_ROOT),
    )
    return result.returncode


def print_help() -> None:
    print("""SOME/IP Dissector — 跨平台启动器

用法:
    python run.py                    查看此帮助
    python run.py web                启动 Web 界面 (http://localhost:8000)
    python run.py debug [选项]       命令行批处理

debug 选项:
    python run.py debug --help       查看完整选项

测试文件位置:
    项目根目录下的 sample.pcap 和 sample.arxml
    或通过 --pcap / --arxml 参数指定""")


def main() -> int:
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print_help()
        return 0

    cmd = args[0]
    rest = args[1:]

    if cmd == "web":
        return cmd_web()
    elif cmd == "debug":
        return cmd_debug(rest)
    else:
        print(f"未知命令: {cmd}")
        print_help()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
