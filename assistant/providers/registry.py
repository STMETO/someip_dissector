"""Provider 注册表与自动选择规则。"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .base import BaseProvider
from .deepseek import DeepSeekProvider
from .generic import GenericProvider

_PROVIDERS: dict[str, BaseProvider] = {
    "deepseek": DeepSeekProvider(),
    "openai_compatible": GenericProvider(),
}


def resolve_provider(config: Any) -> BaseProvider:
    """根据显式配置或 API 主机名选择适配器。"""
    requested = str(getattr(config, "provider", "auto") or "auto")
    if requested != "auto":
        provider = _PROVIDERS.get(requested)
        if provider is None:
            raise ValueError(f"不支持的模型 Provider: {requested}")
        return provider
    hostname = (urlparse(config.api_base).hostname or "").lower()
    if hostname == "api.deepseek.com":
        return _PROVIDERS["deepseek"]
    return _PROVIDERS["openai_compatible"]


def provider_catalog() -> list[dict[str, Any]]:
    """返回前端配置页面可展示的 Provider 能力目录。"""
    rows = [{
        "provider": "auto",
        "label": "Auto",
        "supports_tools": True,
        "supports_stream": True,
        "default_context_window": 65536,
    }]
    rows.extend({
        "provider": item.capabilities.provider,
        "label": item.capabilities.label,
        "supports_tools": item.capabilities.supports_tools,
        "supports_stream": item.capabilities.supports_stream,
        "default_context_window": item.capabilities.default_context_window,
    } for item in _PROVIDERS.values())
    return rows


__all__ = ["provider_catalog", "resolve_provider"]
