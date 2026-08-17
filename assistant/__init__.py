"""AI assistant integration for session-scoped SOME/IP analysis."""

from .schemas import AssistantChatRequest, AssistantConfigRequest
from .service import (
    AssistantError,
    chat,
    clear_all_conversations,
    clear_conversations,
    configure,
    status,
)

__all__ = [
    "AssistantChatRequest",
    "AssistantConfigRequest",
    "AssistantError",
    "chat",
    "clear_all_conversations",
    "clear_conversations",
    "configure",
    "status",
]
