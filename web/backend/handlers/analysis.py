"""Web session adapter for the SOME/IP parsing pipeline.

This module should stay thin:

- receive uploaded files through FastAPI types
- call ``core.pipeline`` for parsing work
- call ``presentation`` for frontend response shapes
- keep in-memory session state for subsequent API calls

Parser construction, ARXML compilation, and payload deserialization deliberately
live outside this module.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from arxml_parsers import ArxmlParser, ServiceRegistry
from core.pipeline import run_parse_pipeline, save_pipeline_exports
from presentation import (
    build_message_detail,
    build_message_summaries,
    render_messages_for_frontend,
)
from web.backend.handlers.upload import cleanup_session, validate_and_save

_SESSIONS_ROOT = Path(__file__).resolve().parent.parent.parent / "sessions"
_SESSION_META = "session.json"
_DESERIALIZED_EXPORT = "deserialized_output.json"


@dataclass
class _SessionState:
    """Cached data for one Web upload/parse session."""

    session_id: str
    session_dir: Path
    messages: list[dict[str, Any]]
    pipeline_result: Any = None  # In-memory parse artifacts, used for later persistence.
    registry: Any = None          # ServiceRegistry, used by diagnostics.
    total_messages: int = 0
    parsed_count: int = 0
    keep_temp: bool = True
    persistent: bool = False
    pcap_name: str = ""
    arxml_name: str = ""
    created_at: str = ""


_sessions: dict[str, _SessionState] = {}


# ═══════════════════════════════════════════════════════════════════
# Upload + parse entry
# ═══════════════════════════════════════════════════════════════════

async def run_upload_and_parse(
    pcap_file: UploadFile,
    arxml_file: UploadFile,
    keep_temp: bool = False,
) -> dict[str, Any]:
    """Save uploaded files, run the core pipeline, and cache frontend messages."""
    persistent = bool(keep_temp)
    pcap_name = pcap_file.filename or "capture.pcap"
    arxml_name = arxml_file.filename or "schema.arxml"
    pcap_path, arxml_path, session_id = await validate_and_save(
        pcap_file, arxml_file, keep_temp)
    session_dir = pcap_path.parent

    # Parsing and export serialization are CPU/disk heavy. Run them outside the
    # FastAPI event loop so already parsed sessions can still be browsed while a
    # new upload is being processed.
    pipeline_result, messages = await run_in_threadpool(
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
        total_messages=len(messages),
        parsed_count=pipeline_result.parsed_count,
        keep_temp=True,
        persistent=persistent,
        pcap_name=pcap_name,
        arxml_name=arxml_name,
        created_at=_utc_now(),
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
# Session / export helpers
# ═══════════════════════════════════════════════════════════════════

def get_session(session_id: str) -> _SessionState | None:
    return _sessions.get(session_id) or _load_session_from_disk(session_id)


def list_sessions() -> list[dict[str, Any]]:
    """Return sessions kept for the currently running Web UI."""
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
    _sessions.pop(session_id, None)
    cleanup_session(session_id)


def persist_session(session_id: str) -> dict[str, Any] | None:
    """Persist a parsed session after the user decides it is worth keeping."""
    state = get_session(session_id)
    if state is None:
        return None

    if not state.persistent:
        if state.pipeline_result is not None:
            save_pipeline_exports(state.session_dir, state.pipeline_result, state.messages)
        else:
            _save_messages_export(state)
        state.persistent = True

    _save_session_meta(state)
    return session_summary(state)


def unpersist_session(session_id: str) -> dict[str, Any] | None:
    """Keep the parsed session in the open UI, but stop saving it to disk.

    The session remains available from ``_sessions`` until the browser closes
    or the user explicitly deletes the local record. Removing only persistence
    artifacts makes the frontend "Unsave" action reversible in the current UI
    lifetime without pretending the parse record is gone.
    """
    state = get_session(session_id)
    if state is None:
        return None

    _remove_persistence_artifacts(state.session_dir)
    state.persistent = False
    return session_summary(state)


def clear_all_sessions(include_persistent: bool = False) -> None:
    """Release Web sessions.

    UI close calls this with the default value: transient sessions are deleted,
    persistent sessions are dropped from memory but their artifacts stay on
    disk for later restoration.
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
    }


def _parse_and_render_session(
    pcap_path: Path,
    arxml_path: Path,
    session_dir: Path,
    persistent: bool,
) -> tuple[Any, list[dict[str, Any]]]:
    """Run the synchronous parse pipeline and build frontend-ready messages."""
    pipeline_result = run_parse_pipeline(pcap_path, arxml_path)
    messages = render_messages_for_frontend(pipeline_result.messages)
    if persistent:
        save_pipeline_exports(session_dir, pipeline_result, messages)
    return pipeline_result, messages


def _save_session_meta(state: _SessionState) -> None:
    meta_path = state.session_dir / _SESSION_META
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(session_summary(state), f, ensure_ascii=False, indent=2)


def _remove_persistence_artifacts(session_dir: Path) -> None:
    """Remove files that make a session survive after the current Web UI."""
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

    state = _SessionState(
        session_id=session_id,
        session_dir=session_dir,
        messages=messages,
        registry=_load_registry(session_dir),
        total_messages=int(meta.get("summary", {}).get("total_messages", len(messages))),
        parsed_count=int(meta.get("summary", {}).get("parsed_count", 0)),
        keep_temp=True,
        persistent=True,
        pcap_name=meta.get("pcap_name", ""),
        arxml_name=meta.get("arxml_name", ""),
        created_at=meta.get("created_at", ""),
    )
    _sessions[session_id] = state
    return state


def _save_messages_export(state: _SessionState) -> None:
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
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "_sessions",
    "build_message_detail",
    "build_message_summaries",
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
