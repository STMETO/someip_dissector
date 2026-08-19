"""AI 问答的脱敏运行记录。

运行记录只保存执行指标，不保存用户问题、System Prompt、模型原始请求体、
API Key 或 Tool 原始结果，便于后续做性能分析和审计。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from time import monotonic
from typing import Any


@dataclass
class ToolCallRecord:
    """单次 Tool 调用的安全指标。"""

    sequence: int
    name: str
    status: str
    duration_ms: int
    result_bytes: int
    original_result_bytes: int
    error_code: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "name": self.name,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "result_bytes": self.result_bytes,
            "original_result_bytes": self.original_result_bytes,
            "error_code": self.error_code,
        }


@dataclass
class AssistantRunRecord:
    """一次问答从接收到结束的结构化运行记录。"""

    request_id: str
    session_id: str
    model: str
    prompt_version: str
    answer_contract_version: str
    started_at: str = field(default_factory=lambda: _utc_now())
    status: str = "running"
    model_rounds: int = 0
    token_usage: dict[str, int] = field(default_factory=dict)
    execution_budget: dict[str, int | float] = field(default_factory=dict)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    invalid_navigation_link_count: int = 0
    error_code: str | None = None
    finished_at: str | None = None
    duration_ms: int = 0
    _started_monotonic: float = field(default_factory=monotonic, repr=False)

    def add_usage(self, value: Any) -> None:
        """合并模型各轮 usage，只接受整数指标。"""
        if not isinstance(value, dict):
            return
        for key, item in value.items():
            if isinstance(item, int) and not isinstance(item, bool):
                self.token_usage[key] = self.token_usage.get(key, 0) + item

    def finish(self, status: str, error_code: str | None = None) -> None:
        """幂等结束记录，确保异常路径也有完整耗时。"""
        if self.finished_at is not None:
            return
        self.status = status
        self.error_code = error_code
        self.finished_at = _utc_now()
        self.duration_ms = max(0, round((monotonic() - self._started_monotonic) * 1000))

    def to_public_dict(self) -> dict[str, Any]:
        """返回可写日志、可回传前端的脱敏结构。"""
        successful = sum(item.status == "success" for item in self.tool_calls)
        return {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "status": self.status,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "answer_contract_version": self.answer_contract_version,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "model_rounds": self.model_rounds,
            "tool_call_count": len(self.tool_calls),
            "tool_success_count": successful,
            "tool_failure_count": len(self.tool_calls) - successful,
            "tool_duration_ms": sum(item.duration_ms for item in self.tool_calls),
            "tool_result_bytes": sum(item.result_bytes for item in self.tool_calls),
            "invalid_navigation_link_count": self.invalid_navigation_link_count,
            "token_usage": dict(self.token_usage),
            "execution_budget": dict(self.execution_budget),
            "error_code": self.error_code,
            "tools": [item.to_public_dict() for item in self.tool_calls],
        }


def log_run_record(logger: logging.Logger, record: AssistantRunRecord) -> None:
    """以单行 JSON 写入日志，避免混入任何原始问答内容。"""
    logger.info(
        "assistant_run %s",
        json.dumps(record.to_public_dict(), ensure_ascii=False, separators=(",", ":")),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = ["AssistantRunRecord", "ToolCallRecord", "log_run_record"]
