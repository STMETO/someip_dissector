"""生产环境 LangGraph 构建、执行与流事件消费。"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Any
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel

from ..agent import build_someip_agent_graph
from ..integrations.langchain.runtime import SomeIpAgentContext
from ..execution.run_record import AssistantRunRecord
from ..integrations.langchain.events import (
    GraphStreamCancelled,
    LangGraphEventAdapter,
    ProgressCallback,
)


@dataclass(frozen=True)
class AgentGraphResult:
    """应用服务需要的有限 Graph 输出。"""

    answer: str
    tools: list[dict[str, Any]]
    state: dict[str, Any]


class AgentGraphExecutionError(RuntimeError):
    """Graph 进入 failed 终态，保留安全错误码供应用层映射。"""

    def __init__(self, message: str, code: str = "graph_failed") -> None:
        super().__init__(message)
        self.code = code


def run_agent_graph(
    *,
    model: BaseChatModel,
    system_prompt: str,
    messages: list[dict[str, Any]],
    context: SomeIpAgentContext,
    run_record: AssistantRunRecord,
    progress: ProgressCallback | None = None,
    cancel_event: Event | None = None,
) -> AgentGraphResult:
    """运行唯一生产 Graph，并同步消费主图及内层 ReAct 事件。

    Graph 每次请求独立编译，因为 System Prompt 包含当前 PCAP 和跨会话授权范围；
    模型、ToolExecutor 和权限对象仅通过 Runtime Context 注入，不进入可序列化 State。
    """
    graph = build_someip_agent_graph(model, system_prompt=system_prompt)
    graph_run_id = uuid4()
    run_record.graph_run_id = str(graph_run_id)
    adapter = LangGraphEventAdapter(run_record, progress, cancel_event)
    stream = graph.stream(
        {"messages": messages},
        context=context,
        config={
            "run_id": graph_run_id,
            "run_name": "someip_assistant",
            # 外层仅有一次有限 Reflection 回路，仍设置硬递归边界防止错误 Edge。
            "recursion_limit": 64,
        },
        stream_mode=["messages", "updates", "values"],
        subgraphs=True,
        version="v2",
    )
    try:
        for event in stream:
            adapter.consume(event)
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()

    state = adapter.final_state
    status = str(state.get("status") or "")
    run_record.graph_status = status or run_record.graph_status
    if status == "cancelled":
        raise GraphStreamCancelled("请求已取消")
    if status == "failed":
        metadata = state.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        raise AgentGraphExecutionError(
            str(state.get("error") or "Agent 执行失败"),
            str(metadata.get("error_code") or "graph_failed"),
        )
    answer = str(state.get("final_answer") or "").strip()
    if not answer:
        error = str(state.get("error") or "Agent 没有返回最终回答")
        raise RuntimeError(error)
    adapter.publish_final_answer(answer)
    return AgentGraphResult(answer=answer, tools=list(adapter.tools), state=state)


__all__ = ["AgentGraphExecutionError", "AgentGraphResult", "run_agent_graph"]
