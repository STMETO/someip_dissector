"""受限 ReAct 子图节点。"""
from __future__ import annotations

from threading import Lock
from typing import Any, Callable

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.runtime import Runtime

from ...execution.model_budget import (
    ModelContextBudgetExceeded,
    ModelRoundBudgetExceeded,
)
from ...integrations.langchain import (
    LANGCHAIN_TOOL_MAP,
    repeated_tool_call_middleware,
    someip_model_budget_middleware,
    someip_tool_middleware,
)
from ..context import SomeIpAgentContext
from ..routing import AgentRoute
from ..state import SomeIpAgentState
from .support import require_context


def make_react_node(
    model: BaseChatModel,
    system_prompt: str,
) -> Callable[..., dict[str, Any]]:
    """创建按 Tool 子集和剩余预算缓存的 ReAct 节点。"""
    agents: dict[tuple[tuple[str, ...], int], Any] = {}
    agents_lock = Lock()

    def diagnostic_agent_node(
        state: SomeIpAgentState,
        runtime: Runtime[SomeIpAgentContext],
    ) -> dict[str, Any]:
        context = require_context(runtime)
        if context.cancel_event is not None and context.cancel_event.is_set():
            return {
                "route": AgentRoute.CANCELLED.value,
                "status": "cancelled",
                "error": "请求已取消",
                "react_messages": [],
            }
        executor = context.tool_executor
        if executor is None:
            return _failure("请求级 ToolExecutor 未初始化", "missing_tool_executor")

        tool_names = tuple(state.get("selected_tools", []))
        unknown = [name for name in tool_names if name not in LANGCHAIN_TOOL_MAP]
        if not tool_names or unknown:
            return _failure(
                "意图没有匹配到可用 Tool" if not unknown else f"Tool 策略包含未知名称: {unknown}",
                "invalid_tool_policy",
            )
        remaining_tools = executor.budget.max_tool_calls - len(executor.run_record.tool_calls)
        if remaining_tools <= 0:
            return _failure("本次问答的 Tool 调用预算已用尽", "tool_call_budget_exceeded")

        cache_key = (tool_names, remaining_tools)
        with agents_lock:
            agent = agents.get(cache_key)
            if agent is None:
                tools = [LANGCHAIN_TOOL_MAP[name] for name in tool_names]
                agent = create_agent(
                    model=model,
                    tools=tools,
                    system_prompt=system_prompt,
                    middleware=[
                        someip_model_budget_middleware,
                        ToolCallLimitMiddleware(
                            run_limit=remaining_tools,
                            exit_behavior="error",
                        ),
                        repeated_tool_call_middleware,
                        someip_tool_middleware,
                    ],
                    context_schema=SomeIpAgentContext,
                    name="someip_diagnostic_react",
                )
                agents[cache_key] = agent

        input_messages = list(state.get("messages", []))
        try:
            result = agent.invoke(
                {"messages": input_messages},
                context=context,
                config={"recursion_limit": 2 * executor.budget.max_model_rounds + 8},
            )
        except (ModelContextBudgetExceeded, ModelRoundBudgetExceeded) as exc:
            code = (
                "model_context_budget_exceeded"
                if isinstance(exc, ModelContextBudgetExceeded)
                else "model_round_budget_exceeded"
            )
            return _failure(str(exc), code)
        except ToolCallLimitExceededError:
            return _failure("本次问答的 Tool 调用预算已用尽", "tool_call_budget_exceeded")
        except Exception as exc:
            return _failure(
                f"ReAct 子图执行失败（{type(exc).__name__}）",
                "react_agent_error",
            )

        generated = list(result.get("messages", []))[len(input_messages):]
        route = (
            AgentRoute.CANCELLED
            if context.cancel_event is not None and context.cancel_event.is_set()
            else AgentRoute.FINISH
        )
        return {
            "messages": generated,
            "react_messages": generated,
            "route": route.value,
            "status": "agent_completed",
            "error": None,
        }

    return diagnostic_agent_node


def _failure(message: str, code: str) -> dict[str, Any]:
    return {
        "route": AgentRoute.FAILED.value,
        "status": "failed",
        "error": message,
        "react_messages": [],
        "metadata": {"error_code": code},
    }


__all__ = ["make_react_node"]
