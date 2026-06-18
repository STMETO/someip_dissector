"""
SOME/IP Dissector Web 界面。

启动方式：
    python web/app.py        # 开发模式，默认 http://localhost:8080
    uvicorn web.app:app      # 生产模式
"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pywebio import start_server
from pywebio.platform.fastapi import webio_routes
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from web.views.upload_view import show_upload_page
from web.utils.session import SessionManager

# FastAPI 应用
app = FastAPI(title="SOME/IP Dissector", description="ARXML + PCAP 全链路解析 Web 界面")

# PyWebIO 路由（挂载到 / ）
app.mount("/static", StaticFiles(directory="web/static"), name="static")
app.router.routes.extend(webio_routes(lambda: show_upload_page(SessionManager())))


def launch_dev():
    """开发模式启动（直接运行脚本）。"""
    start_server(
        lambda: show_upload_page(SessionManager()),
        port=8080,
        debug=True,
        cdn=False,  # 离线模式，不依赖外部 CDN
    )


if __name__ == "__main__":
    launch_dev()
