"""跨外层 LangGraph 与内层 ReAct 子图共享的模型轮次预算。"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import convert_to_openai_messages
from langchain_core.utils.function_calling import convert_to_openai_tool

from ..conversation.context_budget import estimate_request_tokens


class ModelRoundBudgetExceeded(RuntimeError):
    """模型调用达到单次问答硬上限。"""


class ModelContextBudgetExceeded(RuntimeError):
    """模型输入、Tool Schema 与最大输出超过上下文窗口。"""


def reserve_model_round(context: Any) -> None:
    """在发起模型请求前原子地占用一轮预算。

    当前一次 Graph Run 内的模型调用是串行的；Tool 可并发，但不会修改 model_rounds。
    若以后引入并行 Agent，需要把该计数迁移为带锁的运行时预算对象。
    """
    executor = getattr(context, "tool_executor", None)
    if executor is None:
        raise RuntimeError("Agent Runtime 缺少 ToolExecutor，无法读取模型预算")
    record = executor.run_record
    maximum = executor.budget.max_model_rounds
    if record.model_rounds >= maximum:
        raise ModelRoundBudgetExceeded(
            f"单次问答最多允许 {maximum} 轮模型调用"
        )
    record.model_rounds += 1


def enforce_model_context_budget(
    context: Any,
    messages: list[Any],
    tools: list[Any] | tuple[Any, ...] = (),
) -> int:
    """估算标准 LangChain 请求并执行上下文窗口硬限制。

    第六阶段会加入动态裁剪和摘要；当前生产图只负责拒绝超限请求，不能静默丢弃
    Tool 证据或历史消息。
    """
    config = getattr(context, "model_config", None)
    if config is None:
        return 0
    try:
        openai_messages = convert_to_openai_messages(messages)
        if isinstance(openai_messages, dict):
            openai_messages = [openai_messages]
        openai_tools = [
            tool if isinstance(tool, dict) else convert_to_openai_tool(tool)
            for tool in tools
        ]
        estimated = estimate_request_tokens(
            openai_messages,
            openai_tools,
            str(config.model),
        )
    except Exception as exc:
        raise ModelContextBudgetExceeded("无法估算模型上下文 Token") from exc
    if estimated + int(config.max_output_tokens) + 256 > int(config.context_window):
        raise ModelContextBudgetExceeded(
            "当前消息、Tool Schema 和最大输出超过模型上下文窗口"
        )
    return estimated


__all__ = [
    "ModelContextBudgetExceeded",
    "ModelRoundBudgetExceeded",
    "enforce_model_context_budget",
    "reserve_model_round",
]
