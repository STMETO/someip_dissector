"""直接回答、初稿、澄清和终态节点。"""
from __future__ import annotations

from typing import Any, Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langgraph.runtime import Runtime

from ...execution.model_budget import (
    ModelContextBudgetExceeded,
    ModelRoundBudgetExceeded,
    enforce_model_context_budget,
    reserve_model_round,
)
from ...integrations.langchain.runtime import SomeIpAgentContext
from ..intent import SomeIpIntent
from ..routing import AgentRoute
from ..state import SomeIpAgentState
from .support import latest_ai_text, message_text, require_context


def make_direct_answer_node(
    model: BaseChatModel,
    system_prompt: str,
) -> Callable[..., dict[str, Any]]:
    """创建不暴露 Tool 的直接回答节点。"""

    def direct_answer_node(
        state: SomeIpAgentState,
        runtime: Runtime[SomeIpAgentContext],
    ) -> dict[str, Any]:
        context = require_context(runtime)
        try:
            request_messages = [
                SystemMessage(content=system_prompt),
                *state.get("messages", []),
            ]
            enforce_model_context_budget(context, request_messages)
            reserve_model_round(context)
            response = model.invoke(request_messages)
        except (ModelContextBudgetExceeded, ModelRoundBudgetExceeded) as exc:
            code = (
                "model_context_budget_exceeded"
                if isinstance(exc, ModelContextBudgetExceeded)
                else "model_round_budget_exceeded"
            )
            return _failed(str(exc), code)
        except Exception as exc:
            return _failed(
                f"直接回答模型调用失败（{type(exc).__name__}）",
                "direct_answer_error",
            )
        answer = message_text(response).strip()
        if not answer:
            return _failed("模型没有返回可显示的回答", "empty_model_answer")
        return {
            "messages": [response],
            "draft_answer": answer,
            "route": AgentRoute.FINISH.value,
            "status": "drafted",
            "error": None,
        }

    return direct_answer_node


def clarify_node(state: SomeIpAgentState) -> dict[str, Any]:
    """生成不调用模型的稳定澄清问题。"""
    intent = state.get("intent", {})
    question = str(intent.get("clarification_question") or "").strip()
    if not question and intent.get("intent") == SomeIpIntent.SESSION_COMPARISON.value:
        question = "请先在 AI 面板中勾选需要比较的解析记录，然后重新提问。"
    if not question:
        question = "请补充 Service ID、报文索引或字段路径等必要查询条件。"
    return {
        "draft_answer": question,
        "route": AgentRoute.FINISH.value,
        "status": "clarification_required",
        "error": None,
    }


def draft_answer_node(state: SomeIpAgentState) -> dict[str, Any]:
    """把 ReAct 最终回答固定为 Reflection 前的结构化初稿。"""
    answer = latest_ai_text(state.get("react_messages", []))
    if not answer:
        return _failed("ReAct 子图没有生成最终回答", "empty_agent_answer")
    if state.get("route") == AgentRoute.PARTIAL_FAILURE.value:
        answer += "\n\n> 查询限制：本轮存在部分 Tool 失败或结果截断，结论仅基于已返回证据。"
    return {
        "draft_answer": answer,
        "status": "drafted",
        "error": None,
        "route": AgentRoute.FINISH.value,
    }


def finish_node(state: SomeIpAgentState) -> dict[str, Any]:
    """发布经过确定性 Guard 及可选 Reflection 的最终回答。"""
    answer = str(state.get("draft_answer") or "").strip()
    if not answer:
        return _failed("没有可发布的回答", "empty_final_answer")
    return {
        "final_answer": answer,
        "status": "completed",
        "route": AgentRoute.FINISH.value,
        "error": None,
    }


def cancelled_node(_state: SomeIpAgentState) -> dict[str, Any]:
    return {
        "final_answer": "请求已取消。",
        "status": "cancelled",
        "route": AgentRoute.CANCELLED.value,
        "error": "请求已取消",
    }


def failed_node(state: SomeIpAgentState) -> dict[str, Any]:
    message = str(state.get("error") or "Agent 执行失败")
    return {
        "final_answer": f"查询未完成：{message}",
        "status": "failed",
        "route": AgentRoute.FAILED.value,
        "error": message,
    }


def _failed(message: str, code: str) -> dict[str, Any]:
    return {
        "route": AgentRoute.FAILED.value,
        "status": "failed",
        "error": message,
        "metadata": {"error_code": code},
    }


__all__ = [
    "cancelled_node",
    "clarify_node",
    "draft_answer_node",
    "failed_node",
    "finish_node",
    "make_direct_answer_node",
]
