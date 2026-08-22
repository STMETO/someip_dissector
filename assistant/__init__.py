"""绑定解析会话的 SOME/IP AI 助手集成入口。"""
from __future__ import annotations

from typing import Any

from .contracts.requests import (
    AssistantChatRequest,
    AssistantConfigRequest,
    AssistantPersistenceRequest,
)


_SERVICE_EXPORTS = {
    "AssistantError",
    "cancel_request",
    "chat",
    "chat_stream",
    "clear_all_conversations",
    "clear_conversations",
    "configure",
    "conversation_overview",
    "probe",
    "remove_persisted_conversations",
    "set_conversation_persistence",
    "status",
}


def __getattr__(name: str) -> Any:
    """惰性导出应用服务，避免导入 Agent 领域模块时反向加载 Web 编排。"""
    if name not in _SERVICE_EXPORTS:
        raise AttributeError(name)
    from .application import service

    return getattr(service, name)

__all__ = [
    "AssistantChatRequest",
    "AssistantConfigRequest",
    "AssistantPersistenceRequest",
    "AssistantError",
    "cancel_request",
    "chat",
    "chat_stream",
    "clear_all_conversations",
    "clear_conversations",
    "configure",
    "conversation_overview",
    "probe",
    "remove_persisted_conversations",
    "set_conversation_persistence",
    "status",
]
