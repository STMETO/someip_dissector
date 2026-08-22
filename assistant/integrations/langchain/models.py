"""将项目 ModelConfig 映射为 LangChain 标准 ChatModel。"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI

from assistant.llm.config import ModelConfig


_PROVIDER_CATALOG = (
    {
        "provider": "auto",
        "label": "Auto",
        "supports_tools": True,
        "supports_stream": True,
        "default_context_window": 65536,
    },
    {
        "provider": "deepseek",
        "label": "DeepSeek",
        "supports_tools": True,
        "supports_stream": True,
        "default_context_window": 65536,
    },
    {
        "provider": "openai_compatible",
        "label": "OpenAI-compatible",
        "supports_tools": True,
        "supports_stream": True,
        "default_context_window": 65536,
    },
)


class ModelFactoryError(ValueError):
    """模型配置无法映射到受支持的 LangChain ChatModel。"""


class ModelCapabilityError(ModelFactoryError):
    """模型存在，但缺少当前 Agent 主链路要求的能力。"""


class ModelRequestError(RuntimeError):
    """LangChain 模型连接或响应协议错误，可由应用层安全转换。"""


@tool
def _assistant_capability_probe(value: int) -> int:
    """原样返回输入整数，用于验证模型 Tool Calling 能力。"""
    return value


def resolve_chat_model_provider(config: ModelConfig) -> str:
    """解析最终 Provider；显式配置优先，auto 根据 API 主机名判断。"""
    requested = (config.provider or "auto").strip().lower()
    if requested in {"deepseek", "openai_compatible"}:
        return requested
    if requested != "auto":
        raise ModelFactoryError(f"不支持的模型 Provider: {requested}")

    hostname = (urlparse(config.api_base).hostname or "").lower()
    return "deepseek" if hostname == "api.deepseek.com" else "openai_compatible"


def provider_catalog() -> list[dict[str, Any]]:
    """返回配置页使用的 LangChain Provider 静态能力目录。"""
    return [dict(item) for item in _PROVIDER_CATALOG]


def create_chat_model(
    config: ModelConfig,
    *,
    require_tools: bool = False,
    overrides: dict[str, Any] | None = None,
) -> BaseChatModel:
    """根据项目配置创建官方 LangChain ChatModel。

    ``overrides`` 仅供测试或受控的服务端配置覆盖，不接受前端任意透传。工具能力
    校验在创建时完成，避免 ``deepseek-reasoner`` 到 Agent 执行中途才失败。
    """
    if not config.configured:
        raise ModelFactoryError("模型 API Key、API Base 和模型名称必须完整配置")

    provider = resolve_chat_model_provider(config)
    model_name = config.model.strip()
    if require_tools and provider == "deepseek" and model_name.lower() == "deepseek-reasoner":
        raise ModelCapabilityError(
            "deepseek-reasoner 不支持当前 Agent 所需的 Tool Calling；请使用 deepseek-chat"
        )

    common: dict[str, Any] = {
        "model": model_name,
        "api_key": config.api_key,
        "base_url": config.api_base,
        "timeout": config.timeout_seconds,
        "max_retries": 2,
        "streaming": config.stream,
    }
    if provider == "deepseek":
        deepseek_options = {
            **common,
            "max_tokens": config.max_output_tokens,
            "stream_usage": config.stream,
        }
        deepseek_options.update(overrides or {})
        return ChatDeepSeek(**deepseek_options)

    openai_options = {
        **common,
        "max_completion_tokens": config.max_output_tokens,
        # 通用兼容端点未必接受 stream_options，不能默认强制 usage 分片。
        "stream_usage": False,
        "use_responses_api": False,
    }
    openai_options.update(overrides or {})
    return ChatOpenAI(**openai_options)


def probe_chat_model(config: ModelConfig) -> dict[str, Any]:
    """使用 LangChain 标准 ChatModel 验证 Tool Calling 和可选流式能力。"""
    try:
        model = create_chat_model(config, require_tools=True)
        bound = model.bind_tools([_assistant_capability_probe], tool_choice="required")
        messages = [HumanMessage(
            content="Call _assistant_capability_probe with value 1.",
        )]
        supports_stream = False
        if config.stream:
            try:
                response = _collect_streamed_message(bound, messages)
                supports_stream = True
            except Exception:
                # 流式失败后执行一次同步探测，用于区分流能力与 Tool Calling 能力。
                response = bound.invoke(messages)
        else:
            response = bound.invoke(messages)
    except ModelFactoryError:
        raise
    except Exception as exc:
        detail = str(exc).replace(config.api_key, "***")[:600]
        suffix = f": {detail}" if detail else ""
        raise ModelRequestError(
            f"模型能力探测失败（{type(exc).__name__}）{suffix}"
        ) from exc

    calls = list(getattr(response, "tool_calls", []) or [])
    supports_tools = any(
        call.get("name") == _assistant_capability_probe.name
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


def _collect_streamed_message(model: Any, messages: list[HumanMessage]) -> AIMessage:
    """合并 LangChain 标准消息分片，不解析厂商 SSE 私有格式。"""
    combined = None
    for chunk in model.stream(messages):
        combined = chunk if combined is None else combined + chunk
    if combined is None:
        raise ModelRequestError("模型流式响应为空")
    return AIMessage(
        content=combined.content,
        additional_kwargs=combined.additional_kwargs,
        response_metadata=combined.response_metadata,
        tool_calls=list(getattr(combined, "tool_calls", []) or []),
        usage_metadata=getattr(combined, "usage_metadata", None),
    )


__all__ = [
    "ModelCapabilityError",
    "ModelFactoryError",
    "ModelRequestError",
    "create_chat_model",
    "probe_chat_model",
    "provider_catalog",
    "resolve_chat_model_provider",
]
