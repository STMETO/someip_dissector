"""受预算约束的只读 Tool 执行器。

该模块统一负责模型参数校验、调用次数、超时、取消、结果大小和异常转换。
具体 Tool 仍由 ``assistant.tools`` 白名单分发，执行器不接触任意文件或命令。
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from queue import Empty, Queue
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any, Callable

from ..answering.navigation import (
    collect_navigation_links,
    collect_verified_navigation_links,
)
from .run_record import AssistantRunRecord, ToolCallRecord
from ..tools import TOOL_DEFINITIONS, execute_tool, tool_result_json


ToolHandler = Callable[[str, dict[str, Any], str], dict[str, Any]]


class ToolExecutionCancelled(RuntimeError):
    """用户取消问答时中断 Tool 等待。"""


@dataclass(frozen=True)
class ToolExecutionBudget:
    """单次问答共享的模型与 Tool 硬预算。"""

    max_model_rounds: int = 5
    max_tool_calls: int = 12
    single_tool_timeout_seconds: float = 8.0
    cumulative_tool_seconds: float = 30.0
    max_result_bytes: int = 512 * 1024
    max_total_result_bytes: int = 2 * 1024 * 1024

    @classmethod
    def from_environment(cls) -> "ToolExecutionBudget":
        """从环境变量读取并钳制边界，非法值回退默认值。"""
        defaults = cls()
        return cls(
            max_model_rounds=_read_int(
                "AI_MAX_MODEL_ROUNDS", defaults.max_model_rounds, 1, 12
            ),
            max_tool_calls=_read_int(
                "AI_MAX_TOOL_CALLS", defaults.max_tool_calls, 1, 32
            ),
            single_tool_timeout_seconds=_read_float(
                "AI_TOOL_TIMEOUT_SECONDS",
                defaults.single_tool_timeout_seconds,
                0.1,
                120.0,
            ),
            cumulative_tool_seconds=_read_float(
                "AI_TOOL_TOTAL_TIMEOUT_SECONDS",
                defaults.cumulative_tool_seconds,
                0.1,
                300.0,
            ),
            max_result_bytes=_read_int(
                "AI_TOOL_RESULT_MAX_BYTES",
                defaults.max_result_bytes,
                1024,
                8 * 1024 * 1024,
            ),
            max_total_result_bytes=_read_int(
                "AI_TOOL_RESULTS_TOTAL_MAX_BYTES",
                defaults.max_total_result_bytes,
                4096,
                32 * 1024 * 1024,
            ),
        )


@dataclass(frozen=True)
class ToolExecutionOutcome:
    """服务编排层消费的统一 Tool 执行结果。"""

    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    content: str
    links: list[dict[str, Any]]
    verified_links: list[dict[str, Any]]
    ok: bool
    status: str
    error_code: str | None
    duration_ms: int
    result_bytes: int
    original_result_bytes: int


class ToolExecutor:
    """在一轮问答内复用的有状态执行器。"""

    def __init__(
        self,
        session_id: str,
        run_record: AssistantRunRecord,
        *,
        budget: ToolExecutionBudget | None = None,
        tool_handler: ToolHandler = execute_tool,
        logger: logging.Logger | None = None,
    ):
        self.session_id = session_id
        self.run_record = run_record
        self.budget = budget or ToolExecutionBudget.from_environment()
        self._tool_handler = tool_handler
        self._logger = logger or logging.getLogger(__name__)
        self._tool_elapsed_seconds = 0.0
        self._result_bytes = 0
        # LangChain ToolNode 可能并发执行同一轮的多个 Tool。请求级锁保证调用序号、
        # 累计耗时和结果字节预算的检查与更新是原子的。
        self._execution_lock = Lock()
        # 将本次实际生效的预算写入脱敏运行记录，便于定位被限制的原因。
        self.run_record.execution_budget = {
            "max_model_rounds": self.budget.max_model_rounds,
            "max_tool_calls": self.budget.max_tool_calls,
            "single_tool_timeout_seconds": self.budget.single_tool_timeout_seconds,
            "cumulative_tool_seconds": self.budget.cumulative_tool_seconds,
            "max_result_bytes": self.budget.max_result_bytes,
            "max_total_result_bytes": self.budget.max_total_result_bytes,
        }
        self._schemas = {
            str(item.get("function", {}).get("name") or ""): item.get("function", {}).get("parameters", {})
            for item in TOOL_DEFINITIONS
        }

    def execute(
        self,
        name: str,
        raw_arguments: Any,
        cancel_event: Event | None = None,
    ) -> ToolExecutionOutcome:
        """串行进入请求级执行区，并在等待锁时继续响应用户取消。"""
        while not self._execution_lock.acquire(timeout=0.05):
            if cancel_event is not None and cancel_event.is_set():
                raise ToolExecutionCancelled("请求已取消")
        try:
            return self._execute_locked(name, raw_arguments, cancel_event)
        finally:
            self._execution_lock.release()

    def _execute_locked(
        self,
        name: str,
        raw_arguments: Any,
        cancel_event: Event | None,
    ) -> ToolExecutionOutcome:
        """执行一次 Tool；除主动取消外，所有失败都转换为模型可读结果。"""
        sequence = len(self.run_record.tool_calls) + 1
        arguments, argument_error = _parse_arguments(raw_arguments)

        if sequence > self.budget.max_tool_calls:
            return self._failure(
                sequence,
                name,
                arguments,
                "tool_call_budget_exceeded",
                f"单次问答最多允许 {self.budget.max_tool_calls} 次 Tool 调用",
            )

        schema_error = argument_error or self._validate(name, arguments)
        if schema_error:
            return self._failure(
                sequence,
                name,
                arguments,
                "invalid_arguments",
                schema_error,
            )

        remaining_seconds = (
            self.budget.cumulative_tool_seconds - self._tool_elapsed_seconds
        )
        if remaining_seconds <= 0:
            return self._failure(
                sequence,
                name,
                arguments,
                "tool_time_budget_exceeded",
                "本次问答的累计 Tool 耗时预算已用尽",
            )

        timeout_seconds = min(
            self.budget.single_tool_timeout_seconds,
            remaining_seconds,
        )
        started = monotonic()
        try:
            result = self._invoke_with_timeout(
                name,
                arguments,
                timeout_seconds,
                cancel_event,
            )
        except ToolExecutionCancelled:
            elapsed = monotonic() - started
            self._tool_elapsed_seconds += elapsed
            # 取消仍是一条真实调用，运行记录保留指标，但不把结果继续交给模型。
            self.run_record.tool_calls.append(ToolCallRecord(
                sequence=sequence,
                name=name,
                status="cancelled",
                duration_ms=max(0, round(elapsed * 1000)),
                result_bytes=0,
                original_result_bytes=0,
                error_code="cancelled",
            ))
            raise
        except TimeoutError:
            elapsed = monotonic() - started
            self._tool_elapsed_seconds += elapsed
            return self._failure(
                sequence,
                name,
                arguments,
                "tool_timeout",
                f"Tool 在 {timeout_seconds:.2f} 秒内未完成",
                duration_seconds=elapsed,
            )
        except ValueError as exc:
            elapsed = monotonic() - started
            self._tool_elapsed_seconds += elapsed
            return self._failure(
                sequence,
                name,
                arguments,
                "tool_error",
                str(exc),
                duration_seconds=elapsed,
            )
        except Exception as exc:
            elapsed = monotonic() - started
            self._tool_elapsed_seconds += elapsed
            # 日志只记录异常类型，不记录可能包含 Payload 的异常文本。
            self._logger.error("Tool %s 执行异常: %s", name, type(exc).__name__)
            return self._failure(
                sequence,
                name,
                arguments,
                "tool_internal_error",
                "Tool 执行时发生内部错误",
                duration_seconds=elapsed,
            )

        elapsed = monotonic() - started
        self._tool_elapsed_seconds += elapsed
        if not isinstance(result, dict):
            return self._failure(
                sequence,
                name,
                arguments,
                "invalid_tool_result",
                "Tool 必须返回 JSON 对象",
                duration_seconds=elapsed,
            )

        try:
            serialized = tool_result_json(result)
        except (TypeError, ValueError):
            return self._failure(
                sequence,
                name,
                arguments,
                "invalid_tool_result",
                "Tool 返回了无法序列化的 JSON 对象",
                duration_seconds=elapsed,
            )
        original_bytes = len(serialized.encode("utf-8"))
        remaining_bytes = self.budget.max_total_result_bytes - self._result_bytes
        allowed_bytes = min(self.budget.max_result_bytes, remaining_bytes)
        links = collect_navigation_links(name, arguments, result)
        verified_links = collect_verified_navigation_links(name, arguments, result)
        if original_bytes > allowed_bytes:
            reason = (
                "单个 Tool 结果超过大小预算"
                if original_bytes > self.budget.max_result_bytes
                else "本次问答的累计 Tool 结果大小预算已用尽"
            )
            partial = {
                "partial": True,
                "error": {
                    "code": "tool_result_budget_exceeded",
                    "message": reason,
                },
                "original_result_bytes": original_bytes,
                "evidence": verified_links,
                "instruction": "请仅依据保留下来的证据回答，并明确说明查询结果不完整。",
            }
            content = tool_result_json(partial)
            sent_bytes = len(content.encode("utf-8"))
            self._result_bytes += sent_bytes
            return self._record_outcome(
                sequence=sequence,
                name=name,
                arguments=arguments,
                result=partial,
                content=content,
                links=links,
                verified_links=verified_links,
                status="partial",
                error_code="tool_result_budget_exceeded",
                duration_seconds=elapsed,
                result_bytes=sent_bytes,
                original_result_bytes=original_bytes,
            )

        self._result_bytes += original_bytes
        return self._record_outcome(
            sequence=sequence,
            name=name,
            arguments=arguments,
            result=result,
            content=serialized,
            links=links,
            verified_links=verified_links,
            status="success",
            error_code=None,
            duration_seconds=elapsed,
            result_bytes=original_bytes,
            original_result_bytes=original_bytes,
        )

    def _invoke_with_timeout(
        self,
        name: str,
        arguments: dict[str, Any],
        timeout_seconds: float,
        cancel_event: Event | None,
    ) -> dict[str, Any]:
        """在守护线程中执行查询，使主请求能按时响应取消或超时。

        Python 线程无法安全强制终止。超时后只停止等待，后台只读查询可能短暂继续；
        Tool 调用次数和总耗时预算可防止同一问答持续创建任务。
        """
        output: Queue[tuple[bool, Any]] = Queue(maxsize=1)

        def run() -> None:
            try:
                output.put((True, self._tool_handler(name, arguments, self.session_id)))
            except Exception as exc:  # 异常对象仅在线程内传递，不直接写日志。
                output.put((False, exc))

        Thread(target=run, name=f"assistant-tool-{name}", daemon=True).start()
        deadline = monotonic() + timeout_seconds
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise ToolExecutionCancelled("请求已取消")
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError
            try:
                ok, value = output.get(timeout=min(0.05, remaining))
            except Empty:
                continue
            if ok:
                return value
            raise value

    def _validate(self, name: str, arguments: dict[str, Any]) -> str | None:
        schema = self._schemas.get(name)
        if schema is None:
            return f"未知工具: {name}"
        return _validate_object_schema(arguments, schema)

    def _failure(
        self,
        sequence: int,
        name: str,
        arguments: dict[str, Any],
        code: str,
        message: str,
        *,
        duration_seconds: float = 0.0,
    ) -> ToolExecutionOutcome:
        result = {
            "partial": False,
            "error": {"code": code, "message": message},
            "instruction": "该查询未完成，请在回答中明确说明限制，不要补造事实。",
        }
        content = tool_result_json(result)
        result_bytes = len(content.encode("utf-8"))
        self._result_bytes += result_bytes
        return self._record_outcome(
            sequence=sequence,
            name=name,
            arguments=arguments,
            result=result,
            content=content,
            links=[],
            verified_links=[],
            status="failed",
            error_code=code,
            duration_seconds=duration_seconds,
            result_bytes=result_bytes,
            original_result_bytes=0,
        )

    def _record_outcome(
        self,
        *,
        sequence: int,
        name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        content: str,
        links: list[dict[str, Any]],
        verified_links: list[dict[str, Any]],
        status: str,
        error_code: str | None,
        duration_seconds: float,
        result_bytes: int,
        original_result_bytes: int,
    ) -> ToolExecutionOutcome:
        duration_ms = max(0, round(duration_seconds * 1000))
        record = ToolCallRecord(
            sequence=sequence,
            name=name,
            status=status,
            duration_ms=duration_ms,
            result_bytes=result_bytes,
            original_result_bytes=original_result_bytes,
            error_code=error_code,
        )
        self.run_record.tool_calls.append(record)
        return ToolExecutionOutcome(
            name=name,
            arguments=arguments,
            result=result,
            content=content,
            links=links,
            verified_links=verified_links,
            ok=status == "success",
            status=status,
            error_code=error_code,
            duration_ms=duration_ms,
            result_bytes=result_bytes,
            original_result_bytes=original_result_bytes,
        )


def _parse_arguments(value: Any) -> tuple[dict[str, Any], str | None]:
    """严格解析模型参数，解析失败不能静默降级为空对象。"""
    if isinstance(value, dict):
        return value, None
    if not isinstance(value, str) or not value.strip():
        return {}, "Tool arguments 必须是 JSON 对象"
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        return {}, f"Tool arguments 不是合法 JSON: {exc.msg}"
    if not isinstance(parsed, dict):
        return {}, "Tool arguments 必须是 JSON 对象"
    return parsed, None


def _validate_object_schema(value: dict[str, Any], schema: dict[str, Any]) -> str | None:
    """校验当前 Tool 使用到的 JSON Schema 子集，避免增加运行时依赖。"""
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    for key in required:
        if key not in value or value[key] is None or value[key] == "":
            return f"缺少必填参数: {key}"
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(value) - set(properties))
        if unknown:
            return f"包含未定义参数: {', '.join(unknown)}"
    for key, item in value.items():
        if item is None or key not in properties:
            continue
        expected = properties[key].get("type")
        allowed = expected if isinstance(expected, list) else [expected]
        if expected and not any(_matches_type(item, kind) for kind in allowed):
            return f"参数 {key} 类型错误，应为 {' 或 '.join(str(kind) for kind in allowed)}"
    return None


def _matches_type(value: Any, kind: str) -> bool:
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    return True


def _read_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(os.getenv(name, str(default))), maximum))
    except ValueError:
        return default


def _read_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        return max(minimum, min(float(os.getenv(name, str(default))), maximum))
    except ValueError:
        return default


__all__ = [
    "ToolHandler",
    "ToolExecutionBudget",
    "ToolExecutionCancelled",
    "ToolExecutionOutcome",
    "ToolExecutor",
]
