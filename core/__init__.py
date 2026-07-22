"""Core parsing services.

This package contains application-level parsing orchestration.  It deliberately
does not know about FastAPI, upload files, sessions, or Vue response shapes.
"""
from __future__ import annotations

from .pipeline import ParsePipelineResult, run_parse_pipeline, save_pipeline_exports

__all__ = [
    "ParsePipelineResult",
    "run_parse_pipeline",
    "save_pipeline_exports",
]
