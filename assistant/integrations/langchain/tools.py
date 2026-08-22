"""把现有十四个领域查询包装为 LangChain StructuredTool。"""

# 本文件不能启用 postponed annotations。LangGraph 目前通过运行时类型对象识别
# ToolRuntime；若注解被保存为字符串，运行时依赖不会被注入，且可能误传给模型。

from collections.abc import Iterable
from threading import Event
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import create_model

from ...agent.context import SomeIpAgentContext
from ...execution.run_record import AssistantRunRecord
from ...execution.tool_executor import (
    ToolExecutionBudget,
    ToolExecutor,
    ToolHandler,
)
from ...tools import TOOL_DEFINITIONS, execute_tool
from .tool_results import build_tool_response
from .tool_schemas import TOOL_ARGS_SCHEMAS, StrictToolArgs


SomeIpToolRuntime = ToolRuntime[SomeIpAgentContext, dict[str, Any]]


_DESCRIPTION_DETAILS: dict[str, str] = {
    "get_subscription_status": (
        "用于整体或单个 Service 的 SD 健康检查。Service ID 支持 0x 前缀；返回汇总、"
        "服务/EventGroup 状态及代表报文证据，完整时序应继续调用 timeline 工具。"
    ),
    "find_service": (
        "在不知道准确 Service ID 时先调用。支持十六进制、十进制和 ARXML 名称；"
        "结果受 limit 限制，并标明抓包观测与 ARXML 定义信息。"
    ),
    "get_offer_timeline": (
        "已知 Service ID 且需要判断 Offer 生命周期、发布 ECU 或冲突顺序时调用。"
        "返回按时间排序的报文证据，使用 offset/limit 分页。"
    ),
    "get_subscription_timeline": (
        "已知 Service ID 且需要核对 Subscribe/Ack/Nack/Notification 先后关系时调用。"
        "可按 EventGroup、Instance、客户端和时间过滤，返回可分页报文证据。"
    ),
    "search_messages": (
        "需要定位报文索引时调用，再用 get_message_detail 深入单条报文。ID 支持十六进制；"
        "只返回紧凑摘要和分页信息，不返回完整 Payload。"
    ),
    "get_message_detail": (
        "仅在已获得 message_index 后调用。可返回 Header、SD 和 Payload 解析树；"
        "原始 Payload 与深层树受大小限制，证据可导航到消息详情。"
    ),
    "get_notification_statistics": (
        "用于 Notification 数量、频率、间隔或数值字段跳变统计。指定字段时必须同时提供"
        " Service ID 和 Method/Event ID；返回统计范围及代表证据。"
    ),
    "get_payload_field": (
        "仅在已获得 message_index 和准确字段路径后调用。返回目标节点与直接子字段，"
        "适合替代读取完整深层解析树。"
    ),
    "get_request_response_trace": (
        "用于关联 Request/Response、计算响应时间和识别缺失/孤立响应。参数 session_id"
        " 表示 SOME/IP Header Session ID，不是服务端解析会话；结果可分页并带消息证据。"
    ),
    "get_ecu_service_topology": (
        "用于分析 ECU 的 Provider/Consumer 角色、服务和通信对端。可按 ECU IP 或"
        " Service ID 精确过滤，结果受 limit 限制。"
    ),
    "get_arxml_definition": (
        "仅查询一个 Service 的 ARXML 定义。ID 支持十六进制；可缩小到 Method、Event、"
        "EventGroup 或字段路径，不返回整份 ARXML。"
    ),
    "search_payload_values": (
        "用于跨报文检索同一 Payload 字段的值，可组合精确值、文本、数值范围和时间条件。"
        "结果返回命中报文证据并支持 offset/limit 分页。"
    ),
    "get_anomaly_details": (
        "诊断总览出现异常计数后调用，用于展开受影响的 Service、Instance、EventGroup、"
        "客户端和代表报文；支持按异常类型分页。"
    ),
    "compare_sessions": (
        "仅在用户要求跨解析记录比较时调用。目标 session_ids 必须来自本轮服务端授权列表；"
        "最多三个且不包含当前会话，返回结构化差异与会话证据。"
    ),
}


class ToolRuntimeConfigurationError(RuntimeError):
    """LangGraph 未注入请求级 Tool 执行器。"""


def create_tool_context(
    session_id: str,
    run_record: AssistantRunRecord,
    *,
    allowed_session_ids: Iterable[str] = (),
    session_queries: Any = None,
    cancel_event: Event | None = None,
    budget: ToolExecutionBudget | None = None,
    tool_handler: ToolHandler | None = None,
) -> SomeIpAgentContext:
    """创建一次 Agent Run 使用的安全运行时上下文。

    跨会话白名单在闭包中绑定到服务端执行函数。模型只能提交目标会话 ID，无法修改
    ``allowed_session_ids`` 本身。
    """
    allowed = frozenset(str(value) for value in allowed_session_ids if str(value))
    if tool_handler is None:
        def authorized_handler(
            name: str,
            arguments: dict[str, Any],
            current_session_id: str,
        ) -> dict[str, Any]:
            return execute_tool(name, arguments, current_session_id, allowed)

        resolved_handler = authorized_handler
    else:
        # 测试或嵌入方可注入同签名处理器，执行治理仍由 ToolExecutor 负责。
        resolved_handler = tool_handler

    executor = ToolExecutor(
        session_id,
        run_record,
        budget=budget,
        tool_handler=resolved_handler,
    )
    return SomeIpAgentContext(
        session_id=session_id,
        allowed_session_ids=allowed,
        session_queries=session_queries,
        cancel_event=cancel_event,
        tool_executor=executor,
    )


def build_langchain_tools() -> tuple[BaseTool, ...]:
    """按旧注册表顺序创建十四个稳定的 LangChain Tool。"""
    definitions = {
        str(item["function"]["name"]): item["function"]
        for item in TOOL_DEFINITIONS
    }
    if set(definitions) != set(TOOL_ARGS_SCHEMAS):
        missing_schema = sorted(set(definitions) - set(TOOL_ARGS_SCHEMAS))
        missing_definition = sorted(set(TOOL_ARGS_SCHEMAS) - set(definitions))
        raise RuntimeError(
            "LangChain Tool 注册表与 Pydantic Schema 不一致: "
            f"missing_schema={missing_schema}, missing_definition={missing_definition}"
        )

    tools = []
    for name in definitions:
        definition = definitions[name]
        description = (
            f"{str(definition.get('description') or '').strip()} "
            f"{_DESCRIPTION_DETAILS[name]}"
        ).strip()
        tools.append(_create_structured_tool(
            name,
            description,
            TOOL_ARGS_SCHEMAS[name],
        ))
    return tuple(tools)


def get_langchain_tool(name: str) -> BaseTool:
    """按白名单名称读取 Tool，未知名称立即拒绝。"""
    try:
        return LANGCHAIN_TOOL_MAP[name]
    except KeyError as exc:
        raise ValueError(f"未知 LangChain Tool: {name}") from exc


def _create_structured_tool(
    name: str,
    description: str,
    args_schema: type[StrictToolArgs],
) -> StructuredTool:
    """构建绑定 ToolRuntime 的通用适配器，不复制任何领域查询逻辑。"""

    # StructuredTool 使用显式 args_schema 时，注入字段也必须存在于内部 Schema。
    # LangChain 会从模型可见的 tool_call_schema 中自动移除 ToolRuntime，因此模型
    # 仍然只能看到原来的领域参数。
    runtime_args_schema = create_model(
        f"{args_schema.__name__}Runtime",
        __base__=args_schema,
        runtime=(SomeIpToolRuntime, ...),
    )

    def invoke(
        runtime: SomeIpToolRuntime,
        **arguments: Any,
    ) -> tuple[str, dict[str, Any]]:
        context = runtime.context
        if not isinstance(context, SomeIpAgentContext):
            raise ToolRuntimeConfigurationError("ToolRuntime 缺少 SomeIpAgentContext")
        if context.tool_executor is None:
            raise ToolRuntimeConfigurationError("ToolRuntime 缺少请求级 ToolExecutor")
        outcome = context.tool_executor.execute(
            name,
            arguments,
            context.cancel_event,
        )
        return build_tool_response(outcome)

    invoke.__name__ = f"invoke_{name}"
    invoke.__doc__ = description
    return StructuredTool.from_function(
        func=invoke,
        name=name,
        description=description,
        args_schema=runtime_args_schema,
        response_format="content_and_artifact",
    )


LANGCHAIN_TOOLS = build_langchain_tools()
LANGCHAIN_TOOL_MAP: dict[str, BaseTool] = {tool.name: tool for tool in LANGCHAIN_TOOLS}


__all__ = [
    "LANGCHAIN_TOOL_MAP",
    "LANGCHAIN_TOOLS",
    "ToolRuntimeConfigurationError",
    "build_langchain_tools",
    "create_tool_context",
    "get_langchain_tool",
]
