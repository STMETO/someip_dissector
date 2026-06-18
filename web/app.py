from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

# 确保项目根目录可导入
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from utils.logger import setup_logging
from web.handlers.analysis import analyze_capture, build_analysis_payload
from web.handlers.upload import InvalidUploadError, save_upload_bundle
from web.utils.export import save_analysis_export
from web.utils.session import SessionManager
from web.views.detail_view import render_detail_view
from web.views.message_list_view import render_message_list_view
from web.views.upload_view import render_upload_view

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

session_manager = SessionManager()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging(level="INFO")
    session_manager.cleanup_expired()
    yield
    session_manager.cleanup_expired()


app = FastAPI(title="SOME/IP Dissector", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(_render_page())


@app.post("/api/analyze")
async def analyze(
    pcap_file: UploadFile = File(...),
    arxml_file: UploadFile = File(...),
    keep_intermediate: bool = Form(False),
) -> JSONResponse:
    session_manager.cleanup_expired()
    try:
        bundle = await save_upload_bundle(session_manager, pcap_file, arxml_file)
        artifacts = analyze_capture(bundle.pcap_path, bundle.arxml_path)
    except InvalidUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"分析失败: {exc}") from exc

    export_url: str | None = None
    if keep_intermediate:
        export_path = save_analysis_export(bundle.workspace, artifacts.to_export_dict())
        export_url = app.url_path_for(
            "download_export",
            session_id=bundle.workspace.session_id,
            filename=export_path.name,
        )

    payload = build_analysis_payload(
        artifacts,
        session_id=bundle.workspace.session_id,
        export_url=export_url,
    )
    return JSONResponse(payload)


@app.get("/sessions/{session_id}/exports/{filename}", name="download_export")
async def download_export(session_id: str, filename: str) -> FileResponse:
    file_path = session_manager.resolve_export(session_id, filename)
    if file_path is None:
        raise HTTPException(status_code=404, detail="导出文件不存在或已清理")
    return FileResponse(path=file_path, filename=file_path.name, media_type="application/json")


def _render_page() -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SOME/IP Dissector</title>
  <link rel="stylesheet" href="/static/wireshark.css">
  <script defer src="/static/app.js"></script>
    <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.14.9/dist/cdn.min.js"></script>
</head>
<body>
  <div class="shell" x-data="dissectorApp()">
    {render_upload_view()}
    <main class="workspace">
      {render_message_list_view()}
      {render_detail_view()}
    </main>
  </div>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.app:app", host="0.0.0.0", port=8080, reload=True)
