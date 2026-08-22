"""SOME/IP LangGraph 主图构建入口。"""
from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .context import SomeIpAgentContext
from .nodes import (
    cancelled_node,
    clarify_node,
    collect_evidence_node,
    draft_answer_node,
    failed_node,
    finish_node,
    make_classification_node,
    make_bootstrap_node,
    make_direct_answer_node,
    make_react_node,
)
from .routing import AgentRoute, state_route
from .state import SomeIpAgentState


def build_model_smoke_graph(model: BaseChatModel) -> CompiledStateGraph:
    """构建一次模型调用的最小 Graph，用于验证框架、消息 reducer 和流式基础。

    该函数不会接管 Web 主链路，保留它用于快速验证基础 ChatModel 和消息 reducer；
    生产迁移使用下方完整的 ``build_someip_agent_graph``。
    """

    def call_model(state: SomeIpAgentState) -> dict:
        response = model.invoke(state["messages"])
        return {"messages": [response], "status": "completed", "error": None}

    builder = StateGraph(SomeIpAgentState)
    builder.add_node("model", call_model)
    builder.add_edge(START, "model")
    builder.add_edge("model", END)
    return builder.compile()


def build_someip_agent_graph(
    model: BaseChatModel,
    *,
    system_prompt: str,
    classifier_model: BaseChatModel | None = None,
    direct_answer_model: BaseChatModel | None = None,
) -> CompiledStateGraph:
    """构建外层确定性流程和内层受限 ReAct 子图。

    第三阶段仅提供可独立调用的 Graph，不切换 FastAPI 生产入口。第五阶段完成流式
    事件适配和回归后，Web 才会删除旧 `_run_tool_loop`。
    """
    builder = StateGraph(SomeIpAgentState, context_schema=SomeIpAgentContext)
    builder.add_node("bootstrap", make_bootstrap_node(model))
    builder.add_node(
        "classify",
        make_classification_node(classifier_model or model),
    )
    builder.add_node(
        "diagnostic_agent",
        make_react_node(model, system_prompt),
    )
    builder.add_node("collect_evidence", collect_evidence_node)
    builder.add_node(
        "direct_answer",
        make_direct_answer_node(direct_answer_model or model, system_prompt),
    )
    builder.add_node("clarify", clarify_node)
    builder.add_node("draft_answer", draft_answer_node)
    builder.add_node("finish", finish_node)
    builder.add_node("cancelled", cancelled_node)
    builder.add_node("failed", failed_node)

    builder.add_edge(START, "bootstrap")
    builder.add_conditional_edges(
        "bootstrap",
        state_route,
        {
            AgentRoute.USE_TOOLS.value: "classify",
            AgentRoute.CANCELLED.value: "cancelled",
            AgentRoute.FAILED.value: "failed",
        },
    )
    builder.add_conditional_edges(
        "classify",
        state_route,
        {
            AgentRoute.DIRECT_ANSWER.value: "direct_answer",
            AgentRoute.USE_TOOLS.value: "diagnostic_agent",
            AgentRoute.CLARIFY.value: "clarify",
            AgentRoute.CANCELLED.value: "cancelled",
            AgentRoute.FAILED.value: "failed",
        },
    )
    builder.add_conditional_edges(
        "diagnostic_agent",
        state_route,
        {
            AgentRoute.FINISH.value: "collect_evidence",
            AgentRoute.CANCELLED.value: "cancelled",
            AgentRoute.FAILED.value: "failed",
        },
    )
    builder.add_conditional_edges(
        "collect_evidence",
        state_route,
        {
            AgentRoute.FINISH.value: "draft_answer",
            AgentRoute.PARTIAL_FAILURE.value: "draft_answer",
            AgentRoute.CANCELLED.value: "cancelled",
            AgentRoute.FAILED.value: "failed",
        },
    )
    builder.add_conditional_edges(
        "direct_answer",
        state_route,
        {
            AgentRoute.FINISH.value: "finish",
            AgentRoute.FAILED.value: "failed",
        },
    )
    builder.add_edge("clarify", "finish")
    builder.add_conditional_edges(
        "draft_answer",
        state_route,
        {
            AgentRoute.FINISH.value: "finish",
            AgentRoute.FAILED.value: "failed",
        },
    )
    builder.add_edge("finish", END)
    builder.add_edge("cancelled", END)
    builder.add_edge("failed", END)
    return builder.compile()


__all__ = ["build_model_smoke_graph", "build_someip_agent_graph"]
