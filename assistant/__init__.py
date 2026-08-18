"""绑定解析会话的 SOME/IP AI 助手集成入口。"""

from .schemas import (
    AssistantChatRequest,
    AssistantConfigRequest,
    AssistantPersistenceRequest,
)
from .service import (
    AssistantError,
    cancel_request,
    chat,
    chat_stream,
    clear_all_conversations,
    clear_conversations,
    configure,
    conversation_overview,
    probe,
    remove_persisted_conversations,
    set_conversation_persistence,
    status,
)

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
