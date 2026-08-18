"""模型 Provider 适配器的公共基类。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from threading import Event
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from assistant.config import ModelConfig


TextDeltaCallback = Callable[[str], None]


class ProviderRequestError(RuntimeError):
    """Provider 内部的可读请求错误，由业务门面统一转换。"""


@dataclass(frozen=True)
class ProviderCapabilities:
    """Provider 适配器声明的静态能力，不代表具体模型一定支持。"""

    provider: str
    label: str
    supports_tools: bool
    supports_stream: bool
    default_context_window: int


class BaseProvider(ABC):
    """所有厂商适配器共同继承的抽象基类。"""

    capabilities: ProviderCapabilities

    @abstractmethod
    def complete(
        self,
        config: "ModelConfig",
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        on_text_delta: TextDeltaCallback | None = None,
        cancel_event: Event | None = None,
        tool_choice: Any = "auto",
    ) -> dict[str, Any]:
        """返回统一的 assistant message，可选实时回调文本增量。"""
        raise NotImplementedError


__all__ = [
    "BaseProvider",
    "ProviderCapabilities",
    "ProviderRequestError",
    "TextDeltaCallback",
]
