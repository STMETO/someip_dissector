"""通用 OpenAI-compatible 模型服务适配器。"""
from __future__ import annotations

from threading import Event
from typing import Any

from .base import BaseProvider, ProviderCapabilities, TextDeltaCallback
from .openai_compatible import OpenAICompatibleClient


class GenericProvider(BaseProvider):
    """适配没有独立厂商规则的 OpenAI-compatible 服务。"""

    capabilities = ProviderCapabilities(
        provider="openai_compatible",
        label="OpenAI-compatible",
        supports_tools=True,
        supports_stream=True,
        default_context_window=65536,
    )

    def __init__(self, client: OpenAICompatibleClient | None = None) -> None:
        # 允许测试或后续部署注入其他传输实现，默认使用内置 HTTP 客户端。
        self._client = client or OpenAICompatibleClient()

    def complete(
        self,
        config: Any,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        on_text_delta: TextDeltaCallback | None = None,
        cancel_event: Event | None = None,
        tool_choice: Any = "auto",
    ) -> dict[str, Any]:
        """按通用兼容协议发起请求，不添加未经确认的厂商字段。"""
        return self._client.complete(
            config,
            messages,
            tools,
            on_text_delta=on_text_delta,
            cancel_event=cancel_event,
            tool_choice=tool_choice,
        )


__all__ = ["GenericProvider"]
