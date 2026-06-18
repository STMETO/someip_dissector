#!/usr/bin/env python3
"""SOME/IP Dissector 统一启动脚本。

自动构建前端（如未构建），然后启动后端服务。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
FRONTEND_DIR = BASE / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"


def ensure_frontend_built() -> bool:
    """检查前端是否已构建，未构建则自动执行 npm run build。"""
    if (DIST_DIR / "index.html").exists():
        return True

    print("前端未构建，正在自动构建（仅首次需要）...")
    if not (FRONTEND_DIR / "node_modules").exists():
        print("安装依赖...")
        result = subprocess.run(["npm", "install"], cwd=FRONTEND_DIR)
        if result.returncode != 0:
            print("前端依赖安装失败，请手动执行: cd web/frontend && npm install")
            return False

    result = subprocess.run(["npm", "run", "build"], cwd=FRONTEND_DIR)
    if result.returncode != 0:
        print("前端构建失败")
        return False

    print(f"前端构建完成 → {DIST_DIR}")
    return True


def start_server() -> None:
    """启动 FastAPI 后端（自动挂载前端静态文件）。"""
    import uvicorn
    print("启动服务 → http://localhost:8000")
    uvicorn.run("web.backend.app:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    # 确保项目根目录可导入
    sys.path.insert(0, str(BASE.parent))

    if not ensure_frontend_built():
        print("前端构建失败，仅启动 API 服务（/docs 可用）")
    start_server()
