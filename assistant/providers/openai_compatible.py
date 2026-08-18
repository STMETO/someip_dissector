"""OpenAI-compatible Chat Completions 协议客户端。

本文件只负责公共传输协议，不代表任何模型厂商。DeepSeek、通用兼容接口等
Provider 通过组合使用该客户端，避免厂商适配器之间互相继承。
"""
from __future__ import annotations

import json
from threading import Event
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import ProviderRequestError, TextDeltaCallback


class OpenAICompatibleClient:
    """实现兼容协议的请求构造、JSON 响应和 SSE 流式响应解析。"""

    def complete(
        self,
        config: Any,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        on_text_delta: TextDeltaCallback | None = None,
        cancel_event: Event | None = None,
        tool_choice: Any = "auto",
        extra_payload: dict[str, Any] | None = None,
        include_stream_usage: bool = False,
    ) -> dict[str, Any]:
        payload = self._payload(config, messages, tools, tool_choice)
        # 厂商扩展只能由对应 Provider 显式传入，公共客户端不判断厂商名称。
        if extra_payload:
            payload.update(extra_payload)
        use_stream = bool(config.stream and on_text_delta)
        if use_stream:
            payload["stream"] = True
            # 通用兼容服务可能拒绝未知字段，只对明确支持者请求流式 usage。
            if include_stream_usage:
                payload["stream_options"] = {"include_usage": True}
        request = self._request(config, payload, use_stream)
        try:
            with urlopen(request, timeout=config.timeout_seconds) as response:
                if use_stream:
                    return self._read_stream(response, on_text_delta, cancel_event)
                return self._read_json(response)
        except HTTPError as exc:
            raise ProviderRequestError(
                f"模型服务返回 HTTP {exc.code}: {_http_error_detail(exc)}"
            ) from exc
        except URLError as exc:
            raise ProviderRequestError(f"无法连接模型服务: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ProviderRequestError("模型请求超时") from exc
        except UnicodeEncodeError as exc:
            raise ProviderRequestError(
                "模型请求的 HTTP Header 包含非 ASCII 字符，请检查 API Key"
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderRequestError("模型服务返回了无法解析的响应") from exc
        except (OSError, ValueError) as exc:
            raise ProviderRequestError(f"模型请求构造或连接失败: {exc}") from exc

    def _payload(
        self,
        config: Any,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": config.max_output_tokens,
        }
        # 没有 Tool 时不发送空 tools，兼容严格校验请求体的本地模型服务。
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        return payload

    def _request(self, config: Any, payload: dict[str, Any], stream: bool) -> Request:
        return Request(
            _chat_endpoint(config.api_base),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream" if stream else "application/json",
                # HTTP Header 必须保持 ASCII，避免 urllib 在发送阶段编码失败。
                "User-Agent": "someip-dissector-assistant/2.0",
            },
        )

    @staticmethod
    def _read_json(response: Any) -> dict[str, Any]:
        data = json.loads(response.read().decode("utf-8"))
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderRequestError("模型响应中缺少 choices")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise ProviderRequestError("模型响应中缺少 message")
        if isinstance(data.get("usage"), dict):
            message["_usage"] = data["usage"]
        return message

    @staticmethod
    def _read_stream(
        response: Any,
        on_text_delta: TextDeltaCallback | None,
        cancel_event: Event | None,
    ) -> dict[str, Any]:
        content_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] | None = None
        reasoning_parts: list[str] = []
        plain_json_lines: list[str] = []

        for raw_line in response:
            if cancel_event is not None and cancel_event.is_set():
                raise ProviderRequestError("请求已取消")
            line = raw_line.decode("utf-8").strip()
            if not line or line.startswith(":"):
                continue
            if not line.startswith("data:"):
                plain_json_lines.append(line)
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                break
            chunk = json.loads(body)
            if chunk.get("error"):
                error = chunk["error"]
                detail = error.get("message") if isinstance(error, dict) else error
                raise ProviderRequestError(f"模型流式响应错误: {str(detail)[:600]}")
            if isinstance(chunk.get("usage"), dict):
                usage = chunk["usage"]
            choices = chunk.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            delta = choices[0].get("delta") or {}
            text = delta.get("content")
            if isinstance(text, str) and text:
                content_parts.append(text)
                if on_text_delta is not None:
                    on_text_delta(text)
            reasoning = delta.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning:
                reasoning_parts.append(reasoning)
            _merge_tool_call_deltas(tool_calls, delta.get("tool_calls"))

        if plain_json_lines and not content_parts and not tool_calls:
            data = json.loads("".join(plain_json_lines))
            choices = data.get("choices")
            if not isinstance(choices, list) or not choices:
                raise ProviderRequestError("模型流式响应中缺少 choices")
            fallback = choices[0].get("message")
            if not isinstance(fallback, dict):
                raise ProviderRequestError("模型流式响应中缺少 message")
            if isinstance(data.get("usage"), dict):
                fallback["_usage"] = data["usage"]
            text = fallback.get("content")
            if isinstance(text, str) and text and on_text_delta is not None:
                on_text_delta(text)
            return fallback

        message: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(content_parts),
        }
        if tool_calls:
            message["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]
        if reasoning_parts:
            message["reasoning_content"] = "".join(reasoning_parts)
        if usage:
            message["_usage"] = usage
        return message


def _merge_tool_call_deltas(
    target: dict[int, dict[str, Any]],
    deltas: Any,
) -> None:
    """按 index 合并流式 Tool Call，arguments 通常会被拆成多个字符串片段。"""
    if not isinstance(deltas, list):
        return
    for delta in deltas:
        if not isinstance(delta, dict):
            continue
        index = int(delta.get("index", 0))
        row = target.setdefault(index, {
            "id": "",
            "type": "function",
            "function": {"name": "", "arguments": ""},
        })
        if delta.get("id"):
            row["id"] += str(delta["id"])
        if delta.get("type"):
            row["type"] = str(delta["type"])
        function = delta.get("function") or {}
        if function.get("name"):
            row["function"]["name"] += str(function["name"])
        if function.get("arguments"):
            row["function"]["arguments"] += str(function["arguments"])


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


__all__ = [
    "OpenAICompatibleClient",
]
