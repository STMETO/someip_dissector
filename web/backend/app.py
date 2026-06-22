"""SOME/IP Dissector — 统一入口（FastAPI 后端 + Vue 前端静态文件）。"""

from __future__ import annotations

import shutil
from contextlib import asynccontextmanager
from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from web.backend.handlers.analysis import (
    _sessions,
    build_message_detail,
    build_message_summaries,
    clear_session,
    get_export_path,
    get_session,
    run_upload_and_parse,
)

_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
_HAS_FRONTEND = _FRONTEND_DIST.exists() and (_FRONTEND_DIST / "index.html").exists()
_SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sessions"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield  # 启动后什么都不做
    # 关闭：清理所有会话
    for sid in list(_sessions):
        clear_session(sid)
    if _SESSIONS_DIR.exists():
        shutil.rmtree(_SESSIONS_DIR, ignore_errors=True)


app = FastAPI(title="SOME/IP Dissector", lifespan=lifespan)


# ---- API 端点 ----

@app.post("/api/upload")
async def upload(
    pcap_file: UploadFile = File(...),
    arxml_file: UploadFile = File(...),
    keep_temp: bool = Form(False),
) -> JSONResponse:
    try:
        result = await run_upload_and_parse(pcap_file, arxml_file, keep_temp)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"解析失败: {exc}") from exc
    return JSONResponse(result)


@app.get("/api/messages/{session_id}")
async def get_messages(session_id: str) -> JSONResponse:
    state = get_session(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    return JSONResponse(build_message_summaries(state.messages))


@app.get("/api/message/{session_id}/{index}")
async def get_message_detail(session_id: str, index: int) -> JSONResponse:
    state = get_session(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    detail = build_message_detail(state.messages, index)
    if detail is None:
        raise HTTPException(status_code=404, detail="消息索引不存在")
    return JSONResponse(detail)


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str) -> JSONResponse:
    clear_session(session_id)
    return JSONResponse({"ok": True})


@app.get("/api/export/{session_id}/{filename}")
async def download_export(session_id: str, filename: str) -> FileResponse:
    path = get_export_path(session_id, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="导出文件不存在或已过期")
    return FileResponse(path, filename=filename, media_type="application/json")


# ---- 前端静态文件 ----

if _HAS_FRONTEND:
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str = "") -> FileResponse:
        file_path = _FRONTEND_DIST / full_path if full_path else _FRONTEND_DIST / "index.html"
        return FileResponse(file_path if file_path.is_file() else _FRONTEND_DIST / "index.html")
else:
    @app.get("/")
    async def no_frontend():
        return JSONResponse({"message": "前端未构建。运行: cd web/frontend && npm run build"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.backend.app:app", host="0.0.0.0", port=8000, reload=True)
