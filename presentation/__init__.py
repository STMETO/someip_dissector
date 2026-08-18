"""Presentation helpers for API and frontend-facing message shapes.

The parsers produce protocol facts.  Presentation code decides how those facts
are named, summarized, and expanded for the Web UI.
"""
from __future__ import annotations

from .api_views import (
    build_message_detail,
    build_message_detail_from_message,
    build_message_summaries,
    render_messages_for_frontend,
)
from .message_view import build_message_raw_view

__all__ = [
    "build_message_detail",
    "build_message_detail_from_message",
    "build_message_raw_view",
    "build_message_summaries",
    "render_messages_for_frontend",
]
