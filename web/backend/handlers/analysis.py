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

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from core.pipeline import run_parse_pipeline, save_pipeline_exports
from presentation import (
    build_message_detail,
    build_message_summaries,
    render_messages_for_frontend,
)
from web.backend.handlers.upload import cleanup_session, validate_and_save


@dataclass
class _SessionState:
    """Cached data for one Web upload/parse session."""

    session_id: str
    session_dir: Path
    messages: list[dict[str, Any]]
    registry: Any = None          # ServiceRegistry, used by diagnostics.
    total_messages: int = 0
    parsed_count: int = 0
    keep_temp: bool = False


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
    pcap_path, arxml_path, session_id = await validate_and_save(
        pcap_file, arxml_file, keep_temp)
    session_dir = pcap_path.parent

    # Core parsing result has no Web-only raw_view/message_kind fields.
    pipeline_result = run_parse_pipeline(pcap_path, arxml_path)

    # Presentation rendering is separate so other callers can use the pipeline
    # without inheriting frontend response details.
    messages = render_messages_for_frontend(pipeline_result.messages)

    if keep_temp:
        save_pipeline_exports(session_dir, pipeline_result, messages)

    state = _SessionState(
        session_id=session_id,
        session_dir=session_dir,
        messages=messages,
        registry=pipeline_result.registry,
        total_messages=len(messages),
        parsed_count=pipeline_result.parsed_count,
        keep_temp=keep_temp,
    )
    _sessions[session_id] = state

    # Uploaded temp files are not needed after parse unless the user explicitly
    # asks to keep exports/debug artifacts.
    if not keep_temp:
        cleanup_session(session_id)

    return {
        "session_id": session_id,
        "summary": {
            "total_messages": state.total_messages,
            "parsed_count": state.parsed_count,
        },
        "has_export": keep_temp,
    }


# ═══════════════════════════════════════════════════════════════════
# Session / export helpers
# ═══════════════════════════════════════════════════════════════════

def get_session(session_id: str) -> _SessionState | None:
    return _sessions.get(session_id)


def clear_session(session_id: str) -> None:
    state = _sessions.pop(session_id, None)
    if state:
        cleanup_session(session_id)


def get_export_path(session_id: str, filename: str) -> Path | None:
    state = _sessions.get(session_id)
    if not state or not state.keep_temp:
        return None
    p = state.session_dir / "export" / filename
    return p if p.is_file() else None


__all__ = [
    "_sessions",
    "build_message_detail",
    "build_message_summaries",
    "clear_session",
    "get_export_path",
    "get_session",
    "run_upload_and_parse",
]
