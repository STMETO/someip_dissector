"""SOME/IP Dissector — 统一入口（FastAPI 后端 + Vue 前端静态文件）。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from assistant import (
    AssistantChatRequest,
    AssistantConfigRequest,
    AssistantPersistenceRequest,
    AssistantError,
    cancel_request as cancel_assistant_request,
    chat as assistant_chat,
    chat_stream as assistant_chat_stream,
    clear_all_conversations,
    clear_conversations,
    configure as configure_assistant,
    conversation_overview,
    probe as probe_assistant,
    remove_persisted_conversations,
    set_conversation_persistence,
    status as assistant_status,
)
from someip.analysis.queries import ensure_session_queries

from web.backend.handlers.analysis import (
    clear_all_sessions,
    clear_session,
    get_export_path,
    get_session,
    list_sessions,
    persist_session,
    run_upload_and_parse,
    unpersist_session,
)
from someip.presentation import build_message_detail_from_message, build_message_summaries
from web.backend.handlers.sd_diagnostic import get_subscription_report
from web.backend.handlers.signal_timing import get_signal_data, get_signal_meta

_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
_HAS_FRONTEND = _FRONTEND_DIST.exists() and (_FRONTEND_DIST / "index.html").exists()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    clear_all_sessions()
    clear_all_conversations()
    yield
    clear_all_conversations()
    clear_all_sessions()


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


@app.post("/api/session/{session_id}/assistant/chat/stream")
async def stream_assistant(
    session_id: str,
    request: AssistantChatRequest,
) -> StreamingResponse:
    """按 NDJSON 输出模型状态、Tool 进度和最终回答。"""
    return StreamingResponse(
        assistant_chat_stream(
            session_id,
            request.question,
            request.conversation_id,
            request.request_id,
            request.comparison_session_ids,
        ),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/sessions")
async def sessions() -> JSONResponse:
    rows = await run_in_threadpool(list_sessions)
    return JSONResponse({"sessions": rows})


@app.post("/api/sessions/cleanup")
async def cleanup_sessions() -> JSONResponse:
    clear_all_conversations()
    await run_in_threadpool(clear_all_sessions)
    return JSONResponse({"ok": True})


# ---- AI assistant ----

@app.get("/api/assistant/status")
async def get_assistant_status() -> JSONResponse:
    return JSONResponse(assistant_status())


@app.post("/api/assistant/config")
async def set_assistant_config(request: AssistantConfigRequest) -> JSONResponse:
    try:
        result = configure_assistant(request)
    except AssistantError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return JSONResponse(result)


@app.post("/api/assistant/probe")
async def check_assistant_capabilities() -> JSONResponse:
    """发起一次最小请求，验证当前模型是否支持 Tool Calling。"""
    try:
        result = await run_in_threadpool(probe_assistant)
    except AssistantError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return JSONResponse(result)


@app.get("/api/session/{session_id}/assistant/conversations")
async def get_assistant_conversations(session_id: str) -> JSONResponse:
    try:
        result = await run_in_threadpool(conversation_overview, session_id)
    except AssistantError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return JSONResponse(result)


@app.put("/api/session/{session_id}/assistant/persistence")
async def update_assistant_persistence(
    session_id: str,
    request: AssistantPersistenceRequest,
) -> JSONResponse:
    try:
        result = await run_in_threadpool(
            set_conversation_persistence,
            session_id,
            request.enabled,
        )
    except AssistantError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return JSONResponse(result)


@app.post("/api/session/{session_id}/assistant/cancel/{request_id}")
async def cancel_assistant(session_id: str, request_id: str) -> JSONResponse:
    # 请求 ID 与解析记录双重匹配，避免误取消其他会话的并发请求。
    return JSONResponse({
        "cancelled": cancel_assistant_request(request_id, session_id)
    })


@app.post("/api/session/{session_id}/assistant/chat")
async def ask_assistant(
    session_id: str,
    request: AssistantChatRequest,
) -> JSONResponse:
    try:
        result = await run_in_threadpool(
            assistant_chat,
            session_id,
            request.question,
            request.conversation_id,
            # 同步兼容接口也沿用前端请求 ID，便于关联脱敏运行记录。
            request_id=request.request_id,
            comparison_session_ids=request.comparison_session_ids,
        )
    except AssistantError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return JSONResponse(result)


@app.post("/api/session/{session_id}/persist")
async def save_session(session_id: str) -> JSONResponse:
    summary = await run_in_threadpool(persist_session, session_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    return JSONResponse({"session": summary})


@app.post("/api/session/{session_id}/unpersist")
async def unsave_session(session_id: str) -> JSONResponse:
    await run_in_threadpool(remove_persisted_conversations, session_id)
    summary = await run_in_threadpool(unpersist_session, session_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    return JSONResponse({"session": summary})


@app.get("/api/messages/{session_id}")
async def get_messages(session_id: str) -> JSONResponse:
    # 持久化会话首次读取可能需要解析大型 JSON，不能阻塞事件循环。
    state = await run_in_threadpool(get_session, session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    reg = getattr(state, "registry", None)
    indexed_messages = ensure_session_queries(state).messages.all
    messages = await run_in_threadpool(build_message_summaries, indexed_messages, reg)
    return JSONResponse(messages)


@app.get("/api/message/{session_id}/{index}")
async def get_message_detail(session_id: str, index: int) -> JSONResponse:
    state = await run_in_threadpool(get_session, session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    message = ensure_session_queries(state).messages.get(index)
    if message is None:
        raise HTTPException(status_code=404, detail="消息索引不存在")
    detail = build_message_detail_from_message(message)
    return JSONResponse(detail)


# ---- 订阅诊断 ----

@app.get("/api/analysis/subscription-report")
async def subscription_report(session_id: str) -> JSONResponse:
    """返回 SD 订阅诊断报告。"""
    try:
        result = await run_in_threadpool(get_subscription_report, session_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    return JSONResponse(result)


# ---- 信号时序分析 ----

@app.get("/api/signal/meta/{session_id}")
async def signal_meta(session_id: str) -> JSONResponse:
    """返回会话中可绘制信号的三级级联数据（服务→事件→字段路径）。"""
    try:
        data = await run_in_threadpool(get_signal_meta, session_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return JSONResponse(data)


@app.get("/api/signal/data/{session_id}")
async def signal_data(
    session_id: str,
    service_id: int,
    event_id: int,
    field_path: str,
) -> JSONResponse:
    """返回指定字段的时序数据 + 跳变点列表。"""
    try:
        result = await run_in_threadpool(
            get_signal_data,
            session_id,
            service_id,
            event_id,
            field_path,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    return JSONResponse(result)


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str) -> JSONResponse:
    # 持久化会话可能尚未恢复，清理对话时的磁盘读取也必须离开事件循环。
    await run_in_threadpool(clear_conversations, session_id, True)
    await run_in_threadpool(clear_session, session_id)
    return JSONResponse({"ok": True})


@app.get("/api/export/{session_id}/{filename}")
async def download_export(session_id: str, filename: str) -> FileResponse:
    path = await run_in_threadpool(get_export_path, session_id, filename)
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
