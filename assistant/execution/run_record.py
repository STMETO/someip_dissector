"""AI 问答的脱敏运行记录。

运行记录只保存执行指标，不保存用户问题、System Prompt、模型原始请求体、
API Key 或 Tool 原始结果，便于后续做性能分析和审计。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from threading import Lock
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
    reflection_count: int = 0
    reflection_scores: list[float] = field(default_factory=list)
    reflection_failure_reason: str | None = None
    revision_count: int = 0
    supplemental_tool_rounds: int = 0
    supplemental_tool_call_count: int = 0
    graph_run_id: str = ""
    graph_status: str = "running"
    graph_events: list[dict[str, Any]] = field(default_factory=list)
    error_code: str | None = None
    finished_at: str | None = None
    duration_ms: int = 0
    _started_monotonic: float = field(default_factory=monotonic, repr=False)
    _tool_call_lock: Lock = field(default_factory=Lock, repr=False)

    def append_tool_call(self, record: ToolCallRecord) -> None:
        """并发 ToolNode 下原子分配调用序号并追加审计记录。"""
        with self._tool_call_lock:
            record.sequence = len(self.tool_calls) + 1
            self.tool_calls.append(record)

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

    def add_graph_event(self, node: str, status: str) -> None:
        """记录脱敏节点轨迹，不保存 State、消息或 Tool 结果正文。"""
        if len(self.graph_events) >= 128:
            return
        self.graph_events.append({
            "sequence": len(self.graph_events) + 1,
            "node": str(node)[:256],
            "status": str(status or "updated")[:64],
        })
        self.graph_status = str(status or self.graph_status)[:64]

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
            "reflection_count": self.reflection_count,
            "reflection_scores": list(self.reflection_scores),
            "reflection_failure_reason": self.reflection_failure_reason,
            "revision_count": self.revision_count,
            "supplemental_tool_rounds": self.supplemental_tool_rounds,
            "supplemental_tool_call_count": self.supplemental_tool_call_count,
            "graph_run_id": self.graph_run_id,
            "graph_status": self.graph_status,
            "graph_event_count": len(self.graph_events),
            "graph_events": [dict(item) for item in self.graph_events],
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
