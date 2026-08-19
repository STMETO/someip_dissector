"""模型 Provider 兼容门面。

业务编排层只依赖本文件；具体供应商行为位于 ``assistant/llm/providers/``，新增
适配器时不需要修改 Tool 或 Web API。
"""
from __future__ import annotations

from threading import Event
from typing import Any

from .config import ModelConfig
from .providers import ProviderRequestError, TextDeltaCallback, resolve_provider


class ModelProviderError(RuntimeError):
    """允许安全显示给用户的模型连接错误。"""


def create_chat_completion(
    config: ModelConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    on_text_delta: TextDeltaCallback | None = None,
    cancel_event: Event | None = None,
    tool_choice: Any = "auto",
) -> dict[str, Any]:
    """通过注册表选择 Provider，并返回统一的 assistant message。"""
    try:
        provider = resolve_provider(config)
        return provider.complete(
            config,
            messages,
            tools,
            on_text_delta=on_text_delta,
            cancel_event=cancel_event,
            tool_choice=tool_choice,
        )
    except ProviderRequestError as exc:
        raise ModelProviderError(str(exc)) from exc
    except ValueError as exc:
        raise ModelProviderError(str(exc)) from exc


def probe_model(config: ModelConfig) -> dict[str, Any]:
    """发送最小强制 Tool Call，验证具体模型是否遵循工具调用协议。"""
    probe_tool = {
        "type": "function",
        "function": {
            "name": "assistant_capability_probe",
            "description": "Return the supplied integer without modification.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        },
    }
    probe_messages = [{
        "role": "user",
        "content": "Call assistant_capability_probe with value 1.",
    }]
    forced_choice = {
        "type": "function",
        "function": {"name": "assistant_capability_probe"},
    }
    supports_stream = False
    if config.stream:
        try:
            message = create_chat_completion(
                config,
                probe_messages,
                [probe_tool],
                on_text_delta=lambda _delta: None,
                tool_choice=forced_choice,
            )
            supports_stream = True
        except ModelProviderError:
            # 流式失败后再用同步请求区分“模型不支持流”与“完全无法调用模型”。
            message = create_chat_completion(
                config,
                probe_messages,
                [probe_tool],
                tool_choice=forced_choice,
            )
    else:
        message = create_chat_completion(
            config,
            probe_messages,
            [probe_tool],
            tool_choice=forced_choice,
        )
    calls = message.get("tool_calls") or []
    supports_tools = any(
        (call.get("function") or {}).get("name") == "assistant_capability_probe"
        for call in calls
        if isinstance(call, dict)
    )
    return {
        "ok": supports_tools,
        "supports_tools": supports_tools,
        "supports_stream": supports_stream,
        "message": (
            "模型 Tool Calling 与流式输出验证通过"
            if supports_tools and supports_stream
            else "模型 Tool Calling 验证通过，但流式输出未通过"
            if supports_tools
            else "模型未返回要求的 Tool Call"
        ),
    }


__all__ = ["ModelProviderError", "create_chat_completion", "probe_model"]
