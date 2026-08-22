"""将项目 ModelConfig 映射为 LangChain 标准 ChatModel。"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI

from assistant.llm.config import ModelConfig


class ModelFactoryError(ValueError):
    """模型配置无法映射到受支持的 LangChain ChatModel。"""


class ModelCapabilityError(ModelFactoryError):
    """模型存在，但缺少当前 Agent 主链路要求的能力。"""


def resolve_chat_model_provider(config: ModelConfig) -> str:
    """解析最终 Provider；显式配置优先，auto 根据 API 主机名判断。"""
    requested = (config.provider or "auto").strip().lower()
    if requested in {"deepseek", "openai_compatible"}:
        return requested
    if requested != "auto":
        raise ModelFactoryError(f"不支持的模型 Provider: {requested}")

    hostname = (urlparse(config.api_base).hostname or "").lower()
    return "deepseek" if hostname == "api.deepseek.com" else "openai_compatible"


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


__all__ = [
    "ModelCapabilityError",
    "ModelFactoryError",
    "create_chat_model",
    "resolve_chat_model_provider",
]
