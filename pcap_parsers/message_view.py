"""Compatibility wrapper for the raw message view builder.

The raw tree is a presentation concern, not a PCAP parsing concern.  The real
implementation now lives in ``presentation.message_view``.  This wrapper keeps
older imports working while new code imports from the presentation package.
"""
from __future__ import annotations

from presentation.message_view import build_message_raw_view

__all__ = ["build_message_raw_view"]
