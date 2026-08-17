"""绑定解析会话的 SOME/IP AI 助手集成入口。"""

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
