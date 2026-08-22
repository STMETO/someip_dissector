"""最终回答前的确定性证据与导航链接 Guard。"""
from __future__ import annotations

from typing import Any, Callable

from langgraph.runtime import Runtime

from ...answering.navigation import validate_answer_navigation_links
from ...integrations.langchain.runtime import SomeIpAgentContext
from ..intent import SomeIpIntent
from ..reflection import GuardResult
from ..routing import AgentRoute
from ..state import SomeIpAgentState
from .support import require_context


_COMPLEX_INTENTS = {
    SomeIpIntent.GENERAL_DIAGNOSTIC.value,
    SomeIpIntent.SESSION_COMPARISON.value,
}

_ALWAYS_SIMPLE_INTENTS = {
    SomeIpIntent.MODEL_IDENTITY.value,
    SomeIpIntent.CAPABILITIES.value,
    SomeIpIntent.GENERAL_CONVERSATION.value,
}


def make_deterministic_guard_node(
    max_reflections: int,
) -> Callable[..., dict[str, Any]]:
    """创建先清理链接、再决定是否进入 Reflection 的 Guard。"""

    def deterministic_guard_node(
        state: SomeIpAgentState,
        runtime: Runtime[SomeIpAgentContext],
    ) -> dict[str, Any]:
        context = require_context(runtime)
        if context.cancel_event is not None and context.cancel_event.is_set():
            return {
                "route": AgentRoute.CANCELLED.value,
                "status": "cancelled",
                "error": "请求已取消",
            }

        draft = str(state.get("draft_answer") or "").strip()
        if not draft:
            return {
                "route": AgentRoute.FAILED.value,
                "status": "failed",
                "error": "确定性 Guard 没有收到回答初稿",
                "metadata": {"error_code": "guard_empty_draft"},
            }
        raw_evidence = state.get("evidence", [])
        verified = [item for item in raw_evidence if _valid_evidence(item)]
        sanitized, removed = validate_answer_navigation_links(draft, verified)
        issues: list[str] = []
        if removed:
            issues.append(f"已移除 {removed} 个未经本轮证据验证的页面导航链接")
        traces = [
            item for item in state.get("tool_trace", []) if isinstance(item, dict)
        ]
        malformed_evidence = len(raw_evidence) - len(verified)
        if malformed_evidence:
            issues.append(f"忽略 {malformed_evidence} 条格式无效的证据")
        if state.get("selected_tools") and not traces:
            issues.append("诊断回答缺少 Tool 执行轨迹")

        guard = GuardResult(
            passed=not issues,
            invalid_navigation_link_count=removed,
            evidence_count=len(verified),
            tool_trace_count=len(traces),
            issues=issues,
        )
        executor = context.tool_executor
        if executor is not None:
            executor.run_record.invalid_navigation_link_count += removed
        warnings = list(state.get("warnings", []))
        warnings.extend(issues)
        route = (
            AgentRoute.REFLECT
            if _should_reflect(state, max_reflections)
            else AgentRoute.FINISH
        )
        return {
            "draft_answer": sanitized,
            "guard": guard.model_dump(mode="json"),
            "evidence": verified,
            "warnings": list(dict.fromkeys(warnings)),
            "route": route.value,
            "status": "guarded",
            "error": None,
        }

    return deterministic_guard_node


def _should_reflect(state: SomeIpAgentState, maximum: int) -> bool:
    """简单读取和身份问题跳过 LLM Reflection，复杂诊断才进入评审。"""
    if int(state.get("reflection_count", 0)) >= maximum:
        return False
    intent = state.get("intent", {})
    intent_name = str(intent.get("intent") or "")
    # 身份、能力和普通对话属于低风险直接回答。即使分类模型错误标记为复杂，
    # 也不能为这些问题额外消耗 Reflection 轮次。
    if intent_name in _ALWAYS_SIMPLE_INTENTS:
        return False
    if intent_name in _COMPLEX_INTENTS:
        return True
    if intent.get("complexity") == "complex":
        return True
    return intent.get("answer_kind") in {"diagnosis", "report"}


def _valid_evidence(value: Any) -> bool:
    """按导航证据类型校验必需 ID，拒绝模型或异常 Tool 构造的模糊引用。"""
    if not isinstance(value, dict):
        return False
    kind = value.get("kind")
    if kind == "message":
        return _is_non_negative_int(value.get("message_index"))
    if kind == "service":
        return _is_non_negative_int(value.get("service_id"))
    if kind == "eventgroup":
        return (
            _is_non_negative_int(value.get("service_id"))
            and _is_non_negative_int(value.get("eventgroup_id"))
        )
    if kind == "signal":
        return (
            _is_non_negative_int(value.get("service_id"))
            and _is_non_negative_int(value.get("event_id"))
        )
    return False


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


__all__ = ["make_deterministic_guard_node"]
