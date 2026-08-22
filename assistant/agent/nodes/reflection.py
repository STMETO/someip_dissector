"""Evaluator-optimizer Reflection 与限次修订节点。"""
from __future__ import annotations

from hashlib import sha256
import json
from threading import Lock
from typing import Any, Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from ...execution.model_budget import (
    ModelContextBudgetExceeded,
    ModelRoundBudgetExceeded,
    enforce_model_context_budget,
    reserve_model_round,
)
from ...integrations.langchain.runtime import SomeIpAgentContext
from ..reflection import ReflectionResult, RevisionResult
from ..routing import AgentRoute
from ..state import SomeIpAgentState
from .support import require_context


_REFLECTION_PROMPT = """你是 SOME/IP 诊断回答评审器。只输出 ReflectionResult Schema，
不要输出思维过程。依据用户问题、回答初稿、Tool 执行摘要和结构化证据，检查事实覆盖、
无依据结论、证据缺口和格式问题。不得引入输入中不存在的新事实。只有缺失事实必须通过
现有只读 Tool 查询时 needs_more_tools 才能为 true；纯表达问题应给 revision_instructions。"""

_REVISION_PROMPT = """你是 SOME/IP 诊断回答修订器。只输出 RevisionResult Schema。
严格依据给定初稿、Reflection 反馈和本轮证据修改回答，不得增加证据中不存在的服务、
报文、数量、状态、根因或 Payload 值。删除无依据断言，明确事实与推断边界，保留有效
Markdown 结构。不要输出思维过程。"""


def make_reflection_node(
    model: BaseChatModel,
    *,
    max_reflections: int,
) -> Callable[..., dict[str, Any]]:
    """创建结构化评审节点，并限制补充 Tool 与重复反馈循环。"""
    structured_model = None
    model_lock = Lock()

    def reflect_answer_node(
        state: SomeIpAgentState,
        runtime: Runtime[SomeIpAgentContext],
    ) -> dict[str, Any]:
        context = require_context(runtime)
        current_count = int(state.get("reflection_count", 0))
        if current_count >= max_reflections:
            return _finish_with_warning(state, "Reflection 已达到次数上限。")

        payload = _reflection_payload(state)
        messages = [
            SystemMessage(content=_REFLECTION_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
        ]
        try:
            enforce_model_context_budget(context, messages, [ReflectionResult])
            reserve_model_round(context)
        except (ModelContextBudgetExceeded, ModelRoundBudgetExceeded) as exc:
            return _reflection_failure(state, context, str(exc), "reflection_budget_exceeded")

        # 已实际占用模型轮次后立即记录 Reflection 尝试，解析失败也必须可观测。
        next_count = current_count + 1
        record = context.tool_executor.run_record if context.tool_executor else None
        if record is not None:
            record.reflection_count += 1
        try:
            nonlocal structured_model
            if structured_model is None:
                with model_lock:
                    if structured_model is None:
                        structured_model = model.with_structured_output(ReflectionResult)
            result = structured_model.invoke(messages)
            if not isinstance(result, ReflectionResult):
                result = ReflectionResult.model_validate(result)
        except Exception as exc:
            return _reflection_failure(
                state,
                context,
                f"Reflection 调用失败（{type(exc).__name__}）",
                "reflection_model_error",
                reflection_count=next_count,
            )

        if record is not None:
            record.reflection_scores.append(float(result.score))
        result_dict = result.model_dump(mode="json")
        fingerprint = _feedback_fingerprint(result_dict)
        hashes = list(state.get("reflection_feedback_hashes", []))
        duplicate = fingerprint in hashes
        hashes.append(fingerprint)
        base = {
            "reflection": result_dict,
            "reflection_count": next_count,
            "reflection_feedback_hashes": hashes,
            "status": "reflected",
            "error": None,
            "metadata": {
                **state.get("metadata", {}),
                "reflection_score": result.score,
            },
        }
        if duplicate:
            return {
                **base,
                **_warning_update(state, "Reflection 返回了重复反馈，已停止修正循环。"),
                "route": AgentRoute.FINISH.value,
            }
        has_issues = _has_reflection_issues(result)
        if result.passed and not has_issues and not result.needs_more_tools:
            return {**base, "route": AgentRoute.FINISH.value}
        if result.needs_more_tools and _can_query_more(state, context):
            supplemental_rounds = int(state.get("supplemental_tool_rounds", 0)) + 1
            if record is not None:
                record.supplemental_tool_rounds += 1
            return {
                **base,
                "supplemental_tool_rounds": supplemental_rounds,
                "supplemental_query": _supplemental_query(result),
                "route": AgentRoute.USE_TOOLS.value,
            }
        if has_issues and _has_model_budget(context):
            return {**base, "route": AgentRoute.REVISE.value}

        reason = (
            "Reflection 要求补充证据，但剩余预算不足或已经补查过一次。"
            if result.needs_more_tools
            else "Reflection 发现问题，但没有剩余模型预算执行修订。"
        )
        return {
            **base,
            **_warning_update(state, reason),
            "route": AgentRoute.FINISH.value,
        }

    return reflect_answer_node


def make_revision_node(model: BaseChatModel) -> Callable[..., dict[str, Any]]:
    """创建只允许依据现有证据修订表达的 optimizer 节点。"""
    structured_model = None
    model_lock = Lock()

    def revise_answer_node(
        state: SomeIpAgentState,
        runtime: Runtime[SomeIpAgentContext],
    ) -> dict[str, Any]:
        context = require_context(runtime)
        payload = {
            "question": state.get("question", ""),
            "draft_answer": state.get("draft_answer", ""),
            "reflection": state.get("reflection", {}),
            "evidence": state.get("evidence", []),
            "tool_trace": state.get("tool_trace", []),
        }
        messages = [
            SystemMessage(content=_REVISION_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
        ]
        try:
            nonlocal structured_model
            if structured_model is None:
                with model_lock:
                    if structured_model is None:
                        structured_model = model.with_structured_output(RevisionResult)
            enforce_model_context_budget(context, messages, [RevisionResult])
            reserve_model_round(context)
            result = structured_model.invoke(messages)
            if not isinstance(result, RevisionResult):
                result = RevisionResult.model_validate(result)
        except (ModelContextBudgetExceeded, ModelRoundBudgetExceeded) as exc:
            return {
                **_warning_update(state, f"回答未修订：{exc}"),
                "route": AgentRoute.FINISH.value,
                "status": "revision_skipped",
            }
        except Exception as exc:
            return {
                **_warning_update(
                    state,
                    f"回答修订失败（{type(exc).__name__}），保留原初稿。",
                ),
                "route": AgentRoute.FINISH.value,
                "status": "revision_failed",
            }

        next_count = int(state.get("revision_count", 0)) + 1
        if context.tool_executor is not None:
            context.tool_executor.run_record.revision_count += 1
        return {
            "draft_answer": result.answer.strip(),
            "revision_count": next_count,
            "route": AgentRoute.FINISH.value,
            "status": "revised",
            "error": None,
            "metadata": {
                **state.get("metadata", {}),
                "revision_applied_change_count": len(result.applied_changes),
            },
        }

    return revise_answer_node


def _reflection_payload(state: SomeIpAgentState) -> dict[str, Any]:
    """Reflection 仅接收有限事实，不注入完整 Payload 或 Tool artifact。"""
    return {
        "question": state.get("question", ""),
        "intent": state.get("intent", {}),
        "draft_answer": state.get("draft_answer", ""),
        "guard": state.get("guard", {}),
        "evidence": state.get("evidence", [])[:100],
        "tool_trace": state.get("tool_trace", [])[:32],
    }


def _has_reflection_issues(result: ReflectionResult) -> bool:
    return any((
        result.missing_facts,
        result.unsupported_claims,
        result.evidence_gaps,
        result.format_issues,
        result.revision_instructions,
    ))


def _can_query_more(state: SomeIpAgentState, context: SomeIpAgentContext) -> bool:
    executor = context.tool_executor
    if executor is None or int(state.get("supplemental_tool_rounds", 0)) >= 1:
        return False
    if len(executor.run_record.tool_calls) >= executor.budget.max_tool_calls:
        return False
    # 至少保留一次 Tool 决策和一次综合回答模型调用。
    return executor.run_record.model_rounds + 2 <= executor.budget.max_model_rounds


def _has_model_budget(context: SomeIpAgentContext) -> bool:
    executor = context.tool_executor
    return bool(
        executor
        and executor.run_record.model_rounds < executor.budget.max_model_rounds
    )


def _supplemental_query(result: ReflectionResult) -> str:
    findings = [
        *result.missing_facts,
        *result.evidence_gaps,
        *result.revision_instructions,
    ]
    detail = "；".join(findings[:8]) or "补充回答所需的关键抓包证据"
    return f"Reflection 补充查询：{detail}。只调用已授权 Tool，不要推测缺失事实。"


def _feedback_fingerprint(value: dict[str, Any]) -> str:
    payload = {
        key: value.get(key)
        for key in (
            "missing_facts",
            "unsupported_claims",
            "evidence_gaps",
            "format_issues",
            "revision_instructions",
            "needs_more_tools",
        )
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return sha256(encoded).hexdigest()


def _reflection_failure(
    state: SomeIpAgentState,
    context: SomeIpAgentContext,
    message: str,
    code: str,
    reflection_count: int | None = None,
) -> dict[str, Any]:
    record = context.tool_executor.run_record if context.tool_executor else None
    if record is not None:
        record.reflection_failure_reason = code
    update = {
        **_warning_update(state, f"{message}，已保留确定性 Guard 后的回答。"),
        "route": AgentRoute.FINISH.value,
        "status": "reflection_skipped",
        "metadata": {**state.get("metadata", {}), "reflection_error_code": code},
    }
    if reflection_count is not None:
        update["reflection_count"] = reflection_count
    return update


def _finish_with_warning(state: SomeIpAgentState, message: str) -> dict[str, Any]:
    return {
        **_warning_update(state, message),
        "route": AgentRoute.FINISH.value,
        "status": "reflection_limit_reached",
    }


def _warning_update(state: SomeIpAgentState, message: str) -> dict[str, Any]:
    warnings = [*state.get("warnings", []), message]
    return {"warnings": list(dict.fromkeys(warnings))}


__all__ = ["make_reflection_node", "make_revision_node"]
