"""SOME/IP 问题结构化分类节点。"""
from __future__ import annotations

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
from ..intent import (
    IntentClassification,
    SomeIpIntent,
    deterministic_fallback,
    select_tools,
)
from ..routing import AgentRoute
from ..state import SomeIpAgentState
from .support import require_context


_CLASSIFIER_PROMPT = """你是 SOME/IP 诊断问题分类器，只返回给定 Schema。
识别用户意图以及 Service、Method/Event、EventGroup、Instance、message_index、ECU/IP、
Payload 字段路径、时间范围和跨会话范围。涉及当前抓包事实时 requires_tools 必须为 true；
模型身份、能力介绍、普通问候或纯协议概念可以为 false。信息确实不足以形成有效 Tool
参数时设置 needs_clarification，并给出一个简短澄清问题。不得输出 Tool 名称。
如果问题要求综合总结、异常诊断、根因分析或跨会话报告，将 complexity 设为 complex，
并把 answer_kind 设为 diagnosis 或 report；单字段读取和普通检索保持 simple/lookup。"""


def make_classification_node(model: BaseChatModel) -> Callable[..., dict[str, Any]]:
    """创建复用标准 Structured Output 的分类节点。"""
    structured_model = model.with_structured_output(IntentClassification)

    def classify_node(
        state: SomeIpAgentState,
        runtime: Runtime[SomeIpAgentContext],
    ) -> dict[str, Any]:
        context = require_context(runtime)
        question = state.get("question", "").strip()
        fallback_used = False
        try:
            classification_messages = [
                SystemMessage(content=_CLASSIFIER_PROMPT),
                HumanMessage(content=question),
            ]
            enforce_model_context_budget(
                context,
                classification_messages,
                [IntentClassification],
            )
            reserve_model_round(context)
            classification = structured_model.invoke(classification_messages)
            if not isinstance(classification, IntentClassification):
                classification = IntentClassification.model_validate(classification)
        except (ModelContextBudgetExceeded, ModelRoundBudgetExceeded) as exc:
            code = (
                "model_context_budget_exceeded"
                if isinstance(exc, ModelContextBudgetExceeded)
                else "model_round_budget_exceeded"
            )
            return {
                "route": AgentRoute.FAILED.value,
                "status": "failed",
                "error": str(exc),
                "metadata": {"error_code": code},
            }
        except Exception:
            # 分类输出不符合 Schema 时保守回退到确定性规则，不能扩大 Tool 权限。
            classification = deterministic_fallback(question)
            fallback_used = True

        selected = select_tools(classification.intent)
        route = _classification_route(classification, selected, context)
        warnings = list(state.get("warnings", []))
        if fallback_used:
            warnings.append("结构化意图分类失败，已使用保守规则分类。")
        return {
            "intent": classification.model_dump(mode="json"),
            "entities": classification.entities.model_dump(mode="json", exclude_none=True),
            "selected_tools": selected,
            "route": route.value,
            "status": "classified",
            "error": None,
            "warnings": warnings,
            "metadata": {
                **state.get("metadata", {}),
                "classification_fallback": fallback_used,
            },
        }

    return classify_node


def _classification_route(
    classification: IntentClassification,
    selected_tools: list[str],
    context: SomeIpAgentContext,
) -> AgentRoute:
    if classification.needs_clarification:
        return AgentRoute.CLARIFY
    if (
        classification.intent == SomeIpIntent.SESSION_COMPARISON
        and not context.allowed_session_ids
    ):
        return AgentRoute.CLARIFY
    if selected_tools:
        return AgentRoute.USE_TOOLS
    return AgentRoute.DIRECT_ANSWER


__all__ = ["make_classification_node"]
