"""Assistant orchestration and short in-memory conversation context."""
from __future__ import annotations

import json
from threading import Lock
from typing import Any
from uuid import uuid4

from web.backend.handlers.analysis import get_session

from .config import get_model_config, public_config, set_runtime_config
from .provider import ModelProviderError, create_chat_completion
from .schemas import AssistantConfigRequest
from .tools import TOOL_DEFINITIONS, execute_tool, tool_result_json

_MAX_TOOL_ROUNDS = 4
_MAX_HISTORY_MESSAGES = 12
_history_lock = Lock()
_conversations: dict[tuple[str, str], list[dict[str, str]]] = {}


class AssistantError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def status() -> dict[str, object]:
    return public_config()


def configure(request: AssistantConfigRequest) -> dict[str, object]:
    try:
        config = set_runtime_config(
            api_key=request.api_key,
            api_base=request.api_base,
            model=request.model,
        )
    except ValueError as exc:
        raise AssistantError(str(exc), 400) from exc
    return public_config(config)


def chat(
    session_id: str,
    question: str,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    state = get_session(session_id)
    if state is None:
        raise AssistantError("解析会话不存在或已过期", 404)

    config = get_model_config()
    if not config.configured:
        raise AssistantError("请先配置模型 API Key", 503)

    cid = conversation_id or uuid4().hex
    key = (session_id, cid)
    with _history_lock:
        history = list(_conversations.get(key, []))

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(state)},
        *history,
        {"role": "user", "content": question.strip()},
    ]
    used_tools: list[dict[str, Any]] = []

    try:
        answer = _run_tool_loop(config, messages, session_id, used_tools)
    except ModelProviderError as exc:
        raise AssistantError(str(exc), 502) from exc

    with _history_lock:
        next_history = history + [
            {"role": "user", "content": question.strip()},
            {"role": "assistant", "content": answer},
        ]
        _conversations[key] = next_history[-_MAX_HISTORY_MESSAGES:]

    return {
        "conversation_id": cid,
        "answer": answer,
        "tools": used_tools,
        "model": config.model,
    }


def clear_conversations(session_id: str) -> None:
    with _history_lock:
        for key in [key for key in _conversations if key[0] == session_id]:
            _conversations.pop(key, None)


def clear_all_conversations() -> None:
    with _history_lock:
        _conversations.clear()


def _run_tool_loop(
    config: Any,
    messages: list[dict[str, Any]],
    session_id: str,
    used_tools: list[dict[str, Any]],
) -> str:
    for _ in range(_MAX_TOOL_ROUNDS + 1):
        model_message = create_chat_completion(config, messages, TOOL_DEFINITIONS)
        tool_calls = model_message.get("tool_calls") or []
        if not tool_calls:
            content = _message_content(model_message.get("content"))
            if content:
                return content
            raise ModelProviderError("模型没有返回可显示的回答")

        assistant_message = {
            "role": "assistant",
            "content": model_message.get("content") or "",
            "tool_calls": tool_calls,
        }
        # Preserve provider-specific reasoning state when a compatible model
        # returns it, even though the default DeepSeek preset disables thinking.
        if model_message.get("reasoning_content") is not None:
            assistant_message["reasoning_content"] = model_message["reasoning_content"]
        messages.append(assistant_message)
        for call in tool_calls:
            call_id = str(call.get("id") or uuid4().hex)
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            arguments = _parse_arguments(function.get("arguments"))
            try:
                result = execute_tool(name, arguments, session_id)
            except Exception as exc:
                result = {"error": str(exc)}
            used_tools.append({"name": name, "arguments": arguments})
            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "name": name,
                "content": tool_result_json(result),
            })

    raise ModelProviderError("工具调用次数超过限制")


def _system_prompt(state: Any) -> str:
    return f"""你是 SOME/IP 和 SOME/IP-SD 抓包分析助手。
当前解析会话包含 {state.total_messages} 条报文，PCAP 文件为 {state.pcap_name}。

规则：
1. 涉及 Offer、Subscribe、Ack、Notification 或订阅异常的事实时，必须调用工具查询。
2. 工具结果是事实来源，不得虚构抓包中不存在的服务、客户端、数量或状态。
3. 明确区分事实与推断。信息不足时直接说明限制。
4. Service ID 同时显示十六进制形式。回答使用用户提问的语言。
5. 当前只有订阅诊断工具；超出能力时说明尚未提供对应工具。"""


def _parse_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _message_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return "\n".join(part for part in parts if part).strip()
    return ""
