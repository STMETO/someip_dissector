"""SOME/IP LangChain Tool 的横切治理中间件。"""
from __future__ import annotations

from typing import Any, Callable

from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage
from pydantic import ValidationError

from ...execution.tool_executor import ToolExecutionCancelled
from .tool_results import build_tool_error_response
from .tool_schemas import TOOL_ARGS_SCHEMAS


@wrap_tool_call
def someip_tool_middleware(request: Any, handler: Callable[[Any], Any]) -> Any:
    """统一转换 Tool 参数错误，同时保留取消异常的中断语义。

    白名单、调用次数、超时、累计预算和结果字节治理仍由请求级 ``ToolExecutor``
    执行；该 Middleware 负责 LangChain 调用边界上的 Pydantic 错误和未知异常。
    """
    tool_call = request.tool_call
    tool_name = str(tool_call.get("name") or "unknown")
    tool_call_id = str(tool_call.get("id") or "unknown")
    try:
        if request.tool is None:
            return _error_message(
                tool_name,
                tool_call_id,
                "unknown_tool",
                f"未知 Tool: {tool_name}",
            )
        context = getattr(request.runtime, "context", None)
        cancel_event = getattr(context, "cancel_event", None)
        if cancel_event is not None and cancel_event.is_set():
            return _error_message(
                tool_name,
                tool_call_id,
                "cancelled",
                "用户已取消本次问答",
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
                return _error_message(tool_name, tool_call_id, code, message)
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
        return _error_message(tool_name, tool_call_id, "invalid_arguments", details)
    except (TypeError, ValueError) as exc:
        # 参数错误可以反馈给模型修正，但不回传调用栈和内部对象。
        return _error_message(
            tool_name,
            tool_call_id,
            "invalid_arguments",
            str(exc)[:1000] or "Tool 参数无效",
        )
    except Exception:
        return _error_message(
            tool_name,
            tool_call_id,
            "tool_framework_error",
            "Tool 调用框架发生内部错误",
        )


def _error_message(
    tool_name: str,
    tool_call_id: str,
    code: str,
    message: str,
) -> ToolMessage:
    content, artifact = build_tool_error_response(tool_name, code, message)
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


__all__ = ["someip_tool_middleware"]
