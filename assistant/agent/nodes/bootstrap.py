"""LangGraph 请求启动校验节点。"""
from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.runtime import Runtime

from ..context import SomeIpAgentContext
from ..routing import AgentRoute
from ..state import SomeIpAgentState
from .support import latest_user_question, require_context


def make_bootstrap_node(model: BaseChatModel):
    """创建同时校验 ChatModel Tool Calling 能力的启动节点。"""
    supports_tools = type(model).bind_tools is not BaseChatModel.bind_tools

    def bootstrap_node(
        state: SomeIpAgentState,
        runtime: Runtime[SomeIpAgentContext],
    ) -> dict[str, Any]:
        """校验问题、解析会话、模型能力、取消状态和本轮硬预算。"""
        try:
            context = require_context(runtime)
        except RuntimeError as exc:
            return _failed(str(exc), "invalid_runtime")
        if not context.session_id.strip():
            return _failed("解析会话 ID 不能为空", "invalid_session")
        if context.tool_executor is None:
            return _failed("请求级 ToolExecutor 未初始化", "missing_tool_executor")
        if not supports_tools:
            return _failed("当前 ChatModel 不支持 Tool Calling", "tools_not_supported")
        if (
            context.model_config is not None
            and not bool(getattr(context.model_config, "configured", False))
        ):
            return _failed("模型尚未完成配置", "model_not_configured")
        if context.cancel_event is not None and context.cancel_event.is_set():
            return {
                "route": AgentRoute.CANCELLED.value,
                "status": "cancelled",
                "error": "请求已取消",
            }

        question = latest_user_question(state.get("messages", []))
        if not question:
            return _failed("用户问题不能为空", "empty_question")
        budget = context.tool_executor.budget
        return {
            "question": question,
            "route": AgentRoute.USE_TOOLS.value,
            "status": "bootstrapped",
            "error": None,
            "budget": {
                "max_model_rounds": budget.max_model_rounds,
                "max_tool_calls": budget.max_tool_calls,
                "single_tool_timeout_seconds": budget.single_tool_timeout_seconds,
                "cumulative_tool_seconds": budget.cumulative_tool_seconds,
                "max_result_bytes": budget.max_result_bytes,
                "max_total_result_bytes": budget.max_total_result_bytes,
            },
            "warnings": [],
        }

    return bootstrap_node


def _failed(message: str, code: str) -> dict[str, Any]:
    return {
        "route": AgentRoute.FAILED.value,
        "status": "failed",
        "error": message,
        "metadata": {"error_code": code},
    }


__all__ = ["make_bootstrap_node"]
