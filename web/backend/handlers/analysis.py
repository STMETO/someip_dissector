"""SOME/IP 解析流水线的 Web 会话适配层。

本模块只接收上传文件、调用核心解析、保存会话状态并管理持久化文件；协议解析、
ARXML 编译和 Payload 反序列化均位于独立模块中，避免业务逻辑依赖 FastAPI。
"""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from someip.analysis.queries import SessionQueries
from someip.arxml_parsers import ArxmlParser, ServiceRegistry
from someip.core.pipeline import run_parse_pipeline, save_pipeline_exports
from someip.presentation import (
    render_messages_for_frontend,
)
from web.backend.handlers.upload import cleanup_session, validate_and_save
from utils.logger import get_logger

_SESSIONS_ROOT = Path(__file__).resolve().parent.parent.parent / "sessions"
_SESSION_META = "session.json"
_DESERIALIZED_EXPORT = "deserialized_output.json"

logger = get_logger(__name__)


@dataclass
class _SessionState:
    """一组 Web 上传解析记录的内存状态。"""

    session_id: str
    session_dir: Path
    messages: list[dict[str, Any]]
    pipeline_result: Any = None  # 完整 pipeline 产物，供后续持久化使用。
    registry: Any = None         # ARXML ServiceRegistry，供名称解析使用。
    queries: SessionQueries | None = None  # 页面 API 与 AI Tool 共用的只读查询索引。
    total_messages: int = 0
    parsed_count: int = 0
    keep_temp: bool = True
    persistent: bool = False
    pcap_name: str = ""
    arxml_name: str = ""
    created_at: str = ""
    timings: dict[str, float] = field(default_factory=dict)


_sessions: dict[str, _SessionState] = {}
_session_load_locks: dict[str, Lock] = {}
_session_load_locks_guard = Lock()


# ═══════════════════════════════════════════════════════════════════
# 上传与解析入口
# ═══════════════════════════════════════════════════════════════════

async def run_upload_and_parse(
    pcap_file: UploadFile,
    arxml_file: UploadFile,
    keep_temp: bool = False,
) -> dict[str, Any]:
    """保存上传文件、执行核心流水线并缓存前端消息。"""
    persistent = bool(keep_temp)
    pcap_name = pcap_file.filename or "capture.pcap"
    arxml_name = arxml_file.filename or "schema.arxml"
    pcap_path, arxml_path, session_id = await validate_and_save(
        pcap_file, arxml_file, keep_temp)
    session_dir = pcap_path.parent

    # 解析和 JSON 序列化均较耗时，放在线程池中避免阻塞 FastAPI 事件循环，
    # 保证上传新文件时仍可浏览已经完成的会话。
    pipeline_result, messages, queries, timings = await run_in_threadpool(
        _parse_and_render_session,
        pcap_path,
        arxml_path,
        session_dir,
        persistent,
    )

    state = _SessionState(
        session_id=session_id,
        session_dir=session_dir,
        messages=messages,
        pipeline_result=pipeline_result,
        registry=pipeline_result.registry,
        queries=queries,
        total_messages=len(messages),
        parsed_count=pipeline_result.parsed_count,
        keep_temp=True,
        persistent=persistent,
        pcap_name=pcap_name,
        arxml_name=arxml_name,
        created_at=_utc_now(),
        timings=timings,
    )
    _sessions[session_id] = state
    if persistent:
        _save_session_meta(state)

    return {
        "session_id": session_id,
        "summary": {
            "total_messages": state.total_messages,
            "parsed_count": state.parsed_count,
        },
        "has_export": persistent,
        "session": session_summary(state),
    }


# ═══════════════════════════════════════════════════════════════════
# 会话与导出辅助函数
# ═══════════════════════════════════════════════════════════════════

def get_session(session_id: str) -> _SessionState | None:
    """读取内存会话，必要时只执行一次磁盘恢复。

    页面进入时会并发请求消息、诊断和信号数据。按 Session ID 加锁可避免三个
    线程同时反序列化同一份大型 JSON，同时不同会话仍可并行恢复。
    """
    state = _sessions.get(session_id)
    if state is not None:
        return state

    with _session_load_locks_guard:
        load_lock = _session_load_locks.setdefault(session_id, Lock())
    with load_lock:
        state = _sessions.get(session_id)
        if state is not None:
            return state
        state = _load_session_from_disk(session_id)
        if state is not None:
            _sessions[session_id] = state
        return state


def list_sessions() -> list[dict[str, Any]]:
    """返回当前 Web 进程可访问的内存会话和持久化会话。"""
    rows = [session_summary(state) for state in _sessions.values()]
    seen = {row["session_id"] for row in rows}
    if _SESSIONS_ROOT.exists():
        for session_dir in _SESSIONS_ROOT.iterdir():
            if not session_dir.is_dir() or session_dir.name in seen:
                continue
            meta = _read_session_meta(session_dir)
            if meta and meta.get("persistent") is True:
                rows.append(meta)
    rows.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return rows


def clear_session(session_id: str) -> None:
    # 与磁盘恢复使用同一把会话锁，避免删除期间被并发读取重新放回内存。
    with _session_load_locks_guard:
        load_lock = _session_load_locks.setdefault(session_id, Lock())
    with load_lock:
        _sessions.pop(session_id, None)
        cleanup_session(session_id)


def persist_session(session_id: str) -> dict[str, Any] | None:
    """用户确认保留后，将已解析会话持久化到磁盘。"""
    state = get_session(session_id)
    if state is None:
        return None

    started = time.perf_counter()
    if not state.persistent:
        if state.pipeline_result is not None:
            export_timings = save_pipeline_exports(
                state.session_dir,
                state.pipeline_result,
                state.messages,
            )
            state.timings.update(export_timings)
        else:
            state.timings.update(_save_messages_export(state))
        state.persistent = True

    state.timings["last_persist_total_ms"] = _elapsed_ms(started)
    logger.info(
        "Persist timings | session=%s total=%.1fms",
        session_id,
        state.timings["last_persist_total_ms"],
    )
    _save_session_meta(state)
    return session_summary(state)


def unpersist_session(session_id: str) -> dict[str, Any] | None:
    """取消磁盘持久化，但继续在当前 UI 的内存会话中保留解析结果。

    浏览器关闭或用户明确删除前，会话仍可从 ``_sessions`` 读取；因此页面上的
    “取消保存”只删除持久化产物，不会误表示整条解析记录已被删除。
    """
    state = get_session(session_id)
    if state is None:
        return None

    _remove_persistence_artifacts(state.session_dir)
    state.persistent = False
    return session_summary(state)


def clear_all_sessions(include_persistent: bool = False) -> None:
    """释放 Web 会话。

    UI 关闭时使用默认参数：临时会话会被删除，持久化会话只从内存移除，磁盘
    产物保留供下次启动恢复。
    """
    for sid, state in list(_sessions.items()):
        if state.persistent and not include_persistent:
            _sessions.pop(sid, None)
        else:
            clear_session(sid)

    if include_persistent:
        if _SESSIONS_ROOT.exists():
            shutil.rmtree(_SESSIONS_ROOT, ignore_errors=True)
        return

    _cleanup_transient_session_dirs()


def get_export_path(session_id: str, filename: str) -> Path | None:
    state = get_session(session_id)
    if not state:
        return None
    p = state.session_dir / "export" / filename
    return p if p.is_file() else None


def session_summary(state: _SessionState) -> dict[str, Any]:
    return {
        "session_id": state.session_id,
        "pcap_name": state.pcap_name,
        "arxml_name": state.arxml_name,
        "created_at": state.created_at,
        "summary": {
            "total_messages": state.total_messages,
            "parsed_count": state.parsed_count,
        },
        "has_export": state.persistent,
        "persistent": state.persistent,
        "timings": state.timings,
    }


def _parse_and_render_session(
    pcap_path: Path,
    arxml_path: Path,
    session_dir: Path,
    persistent: bool,
) -> tuple[Any, list[dict[str, Any]], SessionQueries, dict[str, float]]:
    """同步执行解析、前端视图构建和会话查询索引构建。"""
    total_start = time.perf_counter()
    pipeline_result = run_parse_pipeline(pcap_path, arxml_path)

    started = time.perf_counter()
    messages = render_messages_for_frontend(pipeline_result.messages)
    timings = dict(pipeline_result.timings)
    timings["frontend_render_ms"] = _elapsed_ms(started)

    # 查询索引与完整 JSON 相互独立，只保存消息引用和字段映射，不复制 Payload。
    started = time.perf_counter()
    queries = SessionQueries(messages, pipeline_result.registry)
    timings["query_index_ms"] = _elapsed_ms(started)

    if persistent:
        timings.update(save_pipeline_exports(session_dir, pipeline_result, messages))

    timings["upload_total_ms"] = _elapsed_ms(total_start)
    pipeline_result.timings.update(timings)
    logger.info(
        "Web render timings | frontend_render=%.1fms query_index=%.1fms upload_total=%.1fms",
        timings["frontend_render_ms"],
        timings["query_index_ms"],
        timings["upload_total_ms"],
    )
    return pipeline_result, messages, queries, timings


def _save_session_meta(state: _SessionState) -> None:
    meta_path = state.session_dir / _SESSION_META
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(session_summary(state), f, ensure_ascii=False, indent=2)


def _remove_persistence_artifacts(session_dir: Path) -> None:
    """删除跨进程持久化文件，但不影响当前 UI 内存中的会话。"""
    meta_path = session_dir / _SESSION_META
    if meta_path.exists():
        meta_path.unlink()
    shutil.rmtree(session_dir / "export", ignore_errors=True)


def _read_session_meta(session_dir: Path) -> dict[str, Any] | None:
    meta_path = session_dir / _SESSION_META
    if meta_path.is_file():
        with meta_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return _legacy_session_meta(session_dir)


def _load_session_from_disk(session_id: str) -> _SessionState | None:
    session_dir = _SESSIONS_ROOT / session_id
    meta = _read_session_meta(session_dir)
    if not meta or meta.get("persistent") is not True:
        return None

    messages = _load_persisted_messages(session_dir)
    if messages is None:
        return None

    registry = _load_registry(session_dir)
    started = time.perf_counter()
    queries = SessionQueries(messages, registry)
    timings = dict(meta.get("timings") or {})
    timings["query_index_restore_ms"] = _elapsed_ms(started)
    state = _SessionState(
        session_id=session_id,
        session_dir=session_dir,
        messages=messages,
        registry=registry,
        queries=queries,
        total_messages=int(meta.get("summary", {}).get("total_messages", len(messages))),
        parsed_count=int(meta.get("summary", {}).get("parsed_count", 0)),
        keep_temp=True,
        persistent=True,
        pcap_name=meta.get("pcap_name", ""),
        arxml_name=meta.get("arxml_name", ""),
        created_at=meta.get("created_at", ""),
        timings=timings,
    )
    _sessions[session_id] = state
    return state


def _save_messages_export(state: _SessionState) -> dict[str, float]:
    started = time.perf_counter()
    export_dir = state.session_dir / "export"
    export_dir.mkdir(exist_ok=True)
    with (export_dir / _DESERIALIZED_EXPORT).open("w", encoding="utf-8") as f:
        json.dump({
            "summary": {
                "total_messages": state.total_messages,
                "parsed_count": state.parsed_count,
            },
            "messages": state.messages,
        }, f, ensure_ascii=False, indent=2)
    return {
        "export_deserialized_json_ms": _elapsed_ms(started),
        "export_total_ms": _elapsed_ms(started),
    }


def _cleanup_transient_session_dirs() -> None:
    if not _SESSIONS_ROOT.exists():
        return
    for session_dir in _SESSIONS_ROOT.iterdir():
        if not session_dir.is_dir():
            continue
        meta = _read_session_meta(session_dir)
        if not meta or meta.get("persistent") is not True:
            shutil.rmtree(session_dir, ignore_errors=True)


def _load_persisted_messages(session_dir: Path) -> list[dict[str, Any]] | None:
    path = session_dir / "export" / _DESERIALIZED_EXPORT
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    messages = data.get("messages")
    return messages if isinstance(messages, list) else None


def _load_registry(session_dir: Path) -> ServiceRegistry | None:
    schema = next(session_dir.glob("schema.*"), None)
    if not schema:
        return None
    try:
        parser = ArxmlParser(schema)
        parser.parse()
        registry = ServiceRegistry()
        registry.build(parser.raw_deployments, parser.raw_interfaces)
        return registry
    except Exception:
        return None


def _legacy_session_meta(session_dir: Path) -> dict[str, Any] | None:
    messages = _load_persisted_messages(session_dir)
    if messages is None:
        return None
    pcap = next(session_dir.glob("capture.*"), None)
    arxml = next(session_dir.glob("schema.*"), None)
    created_at = datetime.fromtimestamp(
        session_dir.stat().st_mtime, timezone.utc).isoformat()
    return {
        "session_id": session_dir.name,
        "pcap_name": pcap.name if pcap else "capture",
        "arxml_name": arxml.name if arxml else "schema",
        "created_at": created_at,
        "summary": {
            "total_messages": len(messages),
            "parsed_count": sum(1 for m in messages if m.get("parse_status") != "unresolved"),
        },
        "has_export": True,
        "persistent": True,
        "timings": {},
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


__all__ = [
    "_sessions",
    "clear_all_sessions",
    "clear_session",
    "get_export_path",
    "get_session",
    "list_sessions",
    "persist_session",
    "run_upload_and_parse",
    "session_summary",
    "unpersist_session",
]
