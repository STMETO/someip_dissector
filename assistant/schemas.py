"""Validated request shapes for the assistant API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AssistantConfigRequest(BaseModel):
    api_key: str | None = Field(default=None, max_length=4096)
    api_base: str = Field(min_length=8, max_length=2048)
    model: str = Field(min_length=1, max_length=256)


class AssistantChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = Field(default=None, max_length=128)
