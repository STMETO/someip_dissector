"""Small OpenAI-compatible chat-completions client.

The MVP intentionally uses the Python standard library, keeping model access
independent from a specific AI SDK. A provider abstraction can replace this
module later without changing the Tool or UI contracts.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .config import ModelConfig


class ModelProviderError(RuntimeError):
    """A safe, user-facing model connection error."""


def create_chat_completion(
    config: ModelConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    endpoint = _chat_endpoint(config.api_base)
    payload = {
        "model": config.model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.1,
    }
    # DeepSeek V4 enables thinking by default. The MVP uses non-thinking mode
    # so the generic Tool loop does not expose or depend on reasoning traces.
    if urlparse(config.api_base).hostname == "api.deepseek.com":
        payload["thinking"] = {"type": "disabled"}
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "someip-dissector-assistant/1.0",
        },
    )

    try:
        with urlopen(request, timeout=config.timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = _http_error_detail(exc)
        raise ModelProviderError(f"模型服务返回 HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ModelProviderError(f"无法连接模型服务: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ModelProviderError("模型请求超时") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelProviderError("模型服务返回了无法解析的响应") from exc

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelProviderError("模型响应中缺少 choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ModelProviderError("模型响应中缺少 message")
    return message


def _chat_endpoint(api_base: str) -> str:
    base = api_base.rstrip("/")
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


def _http_error_detail(exc: HTTPError) -> str:
    try:
        body = json.loads(exc.read().decode("utf-8"))
        error = body.get("error", {})
        detail = error.get("message") if isinstance(error, dict) else error
        return str(detail or "请求失败")[:600]
    except Exception:
        return "请求失败"
