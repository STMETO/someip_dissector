"""SOME/IP LangChain Tool 的横切治理中间件。"""
from __future__ import annotations

import json
from typing import Any, Callable

from langchain.agents.middleware import wrap_model_call, wrap_tool_call
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import ValidationError

from ...execution.tool_executor import ToolExecutionCancelled
from ...execution.run_record import ToolCallRecord
from ...execution.model_budget import enforce_model_context_budget, reserve_model_round
from .tool_results import build_tool_error_response
from .tool_schemas import TOOL_ARGS_SCHEMAS


@wrap_model_call
def someip_model_budget_middleware(request: Any, handler: Callable[[Any], Any]) -> Any:
    """把内层 ReAct 的每次真实模型请求计入全局问答预算。"""
    runtime = getattr(request, "runtime", None)
    context = getattr(runtime, "context", None)
    messages = list(request.messages)
    if request.system_message is not None:
        messages.insert(0, request.system_message)
    enforce_model_context_budget(context, messages, list(request.tools))
    reserve_model_round(context)
    return handler(request)


@wrap_tool_call
def repeated_tool_call_middleware(request: Any, handler: Callable[[Any], Any]) -> Any:
    """阻止模型第三次提交完全相同的 Tool 与参数组合。"""
    call = request.tool_call
    fingerprint = _tool_fingerprint(call.get("name"), call.get("args"))
    repeated = 0
    state = request.state if isinstance(request.state, dict) else {}
    for message in state.get("messages", []):
        if not isinstance(message, AIMessage):
            continue
        for previous in message.tool_calls:
            if _tool_fingerprint(previous.get("name"), previous.get("args")) == fingerprint:
                repeated += 1
    # 当前 AIMessage 已经存在于 Agent State，因此第三次调用时计数为 3。
    if repeated > 2:
        return _error_message(
            str(call.get("name") or "unknown"),
            str(call.get("id") or "unknown"),
            "duplicate_tool_call",
            "相同 Tool 和参数已连续重复，调用被停止；请调整查询条件或基于现有证据回答",
            getattr(request.runtime, "context", None),
        )
    return handler(request)


@wrap_tool_call
def someip_tool_middleware(request: Any, handler: Callable[[Any], Any]) -> Any:
    """统一转换 Tool 参数错误，同时保留取消异常的中断语义。

    白名单、调用次数、超时、累计预算和结果字节治理仍由请求级 ``ToolExecutor``
    执行；该 Middleware 负责 LangChain 调用边界上的 Pydantic 错误和未知异常。
    """
    tool_call = request.tool_call
    tool_name = str(tool_call.get("name") or "unknown")
    tool_call_id = str(tool_call.get("id") or "unknown")
    context = getattr(request.runtime, "context", None)
    try:
        if request.tool is None:
            return _error_message(
                tool_name,
                tool_call_id,
                "unknown_tool",
                f"未知 Tool: {tool_name}",
                context,
            )
        cancel_event = getattr(context, "cancel_event", None)
        if cancel_event is not None and cancel_event.is_set():
            return _error_message(
                tool_name,
                tool_call_id,
                "cancelled",
                "用户已取消本次问答",
                context,
            )
        # ToolNode 默认会先吞掉 Pydantic 异常再生成自由文本。这里提前校验，才能
        # 保证所有失败也遵守统一 JSON 信封，并且不把模型原始参数回显到上下文。
        args_schema = TOOL_ARGS_SCHEMAS.get(tool_name)
        if args_schema is not None:
            args_schema.model_validate(tool_call.get("args") or {})
        response = handler(request)
        if isinstance(response, ToolMessage):
            if response.status == "error":
                code = (
                    "cancelled"
                    if cancel_event is not None and cancel_event.is_set()
                    else "tool_framework_error"
                )
                message = "用户已取消本次问答" if code == "cancelled" else "Tool 调用未完成"
                return _error_message(tool_name, tool_call_id, code, message, context)
            execution = (
                response.artifact.get("execution", {})
                if isinstance(response.artifact, dict)
                else {}
            )
            if execution.get("status") == "failed":
                # 领域 Tool 的受控失败仍保留完整 artifact，但显式标记为 error，
                # 便于后续 LangGraph 路由参数修复或部分失败分支。
                return response.model_copy(update={"status": "error"})
        return response
    except ToolExecutionCancelled:
        raise
    except ValidationError as exc:
        details = _validation_message(exc)
        return _error_message(
            tool_name, tool_call_id, "invalid_arguments", details, context
        )
    except (TypeError, ValueError) as exc:
        # 参数错误可以反馈给模型修正，但不回传调用栈和内部对象。
        return _error_message(
            tool_name,
            tool_call_id,
            "invalid_arguments",
            str(exc)[:1000] or "Tool 参数无效",
            context,
        )
    except Exception:
        return _error_message(
            tool_name,
            tool_call_id,
            "tool_framework_error",
            "Tool 调用框架发生内部错误",
            context,
        )


def _error_message(
    tool_name: str,
    tool_call_id: str,
    code: str,
    message: str,
    context: Any = None,
) -> ToolMessage:
    content, artifact = build_tool_error_response(tool_name, code, message)
    result_bytes = len(content.encode("utf-8"))
    artifact["execution"].update({
        "duration_ms": 0,
        "result_bytes": result_bytes,
        "original_result_bytes": 0,
    })
    executor = getattr(context, "tool_executor", None)
    if executor is not None:
        record = executor.run_record
        record.append_tool_call(ToolCallRecord(
            sequence=0,
            name=tool_name,
            status="failed",
            duration_ms=0,
            result_bytes=result_bytes,
            original_result_bytes=0,
            error_code=code,
        ))
    return ToolMessage(
        content=content,
        tool_call_id=tool_call_id,
        name=tool_name,
        status="error",
        artifact=artifact,
    )


def _validation_message(exc: ValidationError) -> str:
    """生成不包含模型原始输入值的简洁 Pydantic 错误。"""
    errors = []
    for item in exc.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in item.get("loc", ())) or "arguments"
        errors.append(f"{location}: {item.get('msg', '参数无效')}")
    return "; ".join(errors)[:2000] or "Tool 参数校验失败"


def _tool_fingerprint(name: Any, arguments: Any) -> str:
    """用稳定 JSON 生成重复调用指纹，不依赖字典字段顺序。"""
    try:
        payload = json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        payload = "<invalid>"
    return f"{str(name or '')}:{payload}"


__all__ = [
    "repeated_tool_call_middleware",
    "someip_model_budget_middleware",
    "someip_tool_middleware",
]
