"""DeepSeek 官方 Chat Completions 适配器。"""
from __future__ import annotations

from threading import Event
from typing import Any

from .base import BaseProvider, ProviderCapabilities, TextDeltaCallback
from .openai_compatible import OpenAICompatibleClient


class DeepSeekProvider(BaseProvider):
    """直接实现 Provider 基类，并组合复用兼容协议客户端。"""

    capabilities = ProviderCapabilities(
        provider="deepseek",
        label="DeepSeek",
        supports_tools=True,
        supports_stream=True,
        default_context_window=65536,
    )

    def __init__(self, client: OpenAICompatibleClient | None = None) -> None:
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
        """添加 DeepSeek 扩展参数后交给公共协议客户端发送。"""
        return self._client.complete(
            config,
            messages,
            tools,
            on_text_delta=on_text_delta,
            cancel_event=cancel_event,
            tool_choice=tool_choice,
            # 本项目只消费可见回答和 Tool Calling，不保存模型内部思考文本。
            extra_payload={"thinking": {"type": "disabled"}},
            # DeepSeek 支持在流式结束分片中返回本次请求的 usage。
            include_stream_usage=True,
        )


__all__ = ["DeepSeekProvider"]
