"""Reflection、确定性 Guard 与修订的结构化契约。"""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


ShortFinding = Annotated[str, Field(min_length=1, max_length=500)]


class ReflectionResult(BaseModel):
    """评审器只输出问题清单，不保存隐藏推理过程。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    missing_facts: list[ShortFinding] = Field(default_factory=list, max_length=8)
    unsupported_claims: list[ShortFinding] = Field(default_factory=list, max_length=8)
    evidence_gaps: list[ShortFinding] = Field(default_factory=list, max_length=8)
    format_issues: list[ShortFinding] = Field(default_factory=list, max_length=8)
    revision_instructions: list[ShortFinding] = Field(default_factory=list, max_length=8)
    needs_more_tools: bool = False


class RevisionResult(BaseModel):
    """修订模型的有限输出，不接受新的证据或 Tool 结果。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    answer: str = Field(min_length=1, max_length=50_000)
    applied_changes: list[str] = Field(default_factory=list, max_length=12)


class GuardResult(BaseModel):
    """确定性校验结果，可安全写入 Graph State 和运行记录。"""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    invalid_navigation_link_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    tool_trace_count: int = Field(ge=0)
    issues: list[str] = Field(default_factory=list, max_length=20)


__all__ = ["GuardResult", "ReflectionResult", "RevisionResult"]
