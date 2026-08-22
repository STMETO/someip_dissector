"""LangGraph 图构建入口。第一阶段只提供无 Tool 的基础图。"""
from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .state import SomeIpAgentState


def build_model_smoke_graph(model: BaseChatModel) -> CompiledStateGraph:
    """构建一次模型调用的最小 Graph，用于验证框架、消息 reducer 和流式基础。

    该函数不会接管 Web 主链路。第三阶段会在相同入口扩展 ReAct、证据与
    Reflection 节点，因此第一阶段的测试不是一次性脚手架。
    """

    def call_model(state: SomeIpAgentState) -> dict:
        response = model.invoke(state["messages"])
        return {"messages": [response], "status": "completed", "error": None}

    builder = StateGraph(SomeIpAgentState)
    builder.add_node("model", call_model)
    builder.add_edge(START, "model")
    builder.add_edge("model", END)
    return builder.compile()


__all__ = ["build_model_smoke_graph"]
