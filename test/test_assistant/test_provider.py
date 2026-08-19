"""模型 Provider 的 HTTP 请求构造和异常转换测试。"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from assistant.llm.config import ModelConfig
from assistant.llm.gateway import ModelProviderError, create_chat_completion
from assistant.llm.providers.base import BaseProvider
from assistant.llm.providers.deepseek import DeepSeekProvider
from assistant.llm.providers.generic import GenericProvider


class _Response:
    """提供 urllib 上下文管理器所需的最小模拟响应。"""

    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body


class _StreamResponse:
    """模拟按行返回的 OpenAI SSE 响应。"""

    def __init__(self, chunks: list[dict]):
        self._lines = [
            f"data: {json.dumps(chunk)}\n".encode("utf-8")
            for chunk in chunks
        ] + [b"data: [DONE]\n"]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __iter__(self):
        return iter(self._lines)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.config = ModelConfig(
            api_key="test-key",
            api_base="https://api.deepseek.com",
            model="test-model",
            timeout_seconds=5.0,
            source="runtime",
        )

    def test_vendor_providers_share_only_the_base_class(self):
        """厂商适配器必须并列继承基类，不能形成厂商之间的继承关系。"""
        self.assertTrue(issubclass(DeepSeekProvider, BaseProvider))
        self.assertTrue(issubclass(GenericProvider, BaseProvider))
        self.assertNotIn(GenericProvider, DeepSeekProvider.__mro__)
        self.assertNotIn(DeepSeekProvider, GenericProvider.__mro__)

    def test_request_headers_are_ascii_and_response_is_parsed(self):
        """防止排版连字符等 Unicode 字符再次进入 HTTP Header。"""
        response = _Response({
            "choices": [{"message": {"role": "assistant", "content": "ok"}}]
        })
        with patch(
            "assistant.llm.providers.openai_compatible.urlopen",
            return_value=response,
        ) as mocked:
            message = create_chat_completion(
                self.config,
                [{"role": "user", "content": "你好"}],
                [],
            )

        request = mocked.call_args.args[0]
        for name, value in request.header_items():
            name.encode("ascii")
            value.encode("ascii")
        self.assertEqual(request.get_header("User-agent"), "someip-dissector-assistant/2.0")
        self.assertEqual(message["content"], "ok")

    def test_deepseek_provider_adds_only_vendor_specific_fields(self):
        """DeepSeek 扩展字段应位于独立适配器，不能污染通用兼容请求。"""
        response = _Response({
            "choices": [{"message": {"role": "assistant", "content": "ok"}}]
        })
        with patch(
            "assistant.llm.providers.openai_compatible.urlopen",
            return_value=response,
        ) as mocked:
            create_chat_completion(
                self.config,
                [{"role": "user", "content": "test"}],
                [],
            )

        deepseek_payload = json.loads(mocked.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(deepseek_payload["thinking"], {"type": "disabled"})

        generic_config = ModelConfig(
            api_key="test-key",
            api_base="https://llm.example.com/v1",
            model="test-model",
            timeout_seconds=5.0,
            source="runtime",
            provider="openai_compatible",
        )
        with patch(
            "assistant.llm.providers.openai_compatible.urlopen",
            return_value=response,
        ) as mocked:
            create_chat_completion(
                generic_config,
                [{"role": "user", "content": "test"}],
                [],
            )

        generic_payload = json.loads(mocked.call_args.args[0].data.decode("utf-8"))
        self.assertNotIn("thinking", generic_payload)

    def test_header_encoding_error_becomes_provider_error(self):
        """底层编码错误必须转换成可由 FastAPI 返回的业务异常。"""
        encoding_error = UnicodeEncodeError("ascii", "密钥", 0, 1, "not ascii")
        with patch(
            "assistant.llm.providers.openai_compatible.urlopen",
            side_effect=encoding_error,
        ):
            with self.assertRaisesRegex(ModelProviderError, "HTTP Header"):
                create_chat_completion(
                    self.config,
                    [{"role": "user", "content": "test"}],
                    [],
                )

    def test_stream_merges_text_and_tool_call_fragments(self):
        response = _StreamResponse([
            {"choices": [{"delta": {"content": "查询"}}]},
            {"choices": [{"delta": {"content": "中"}}]},
            {"choices": [{"delta": {"tool_calls": [{
                "index": 0,
                "id": "call-1",
                "type": "function",
                "function": {"name": "search_", "arguments": '{"service_'},
            }]}}]},
            {"choices": [{"delta": {"tool_calls": [{
                "index": 0,
                "function": {"name": "messages", "arguments": 'id":"0x0A01"}'},
            }]}}]},
            {"choices": [], "usage": {"total_tokens": 12}},
        ])
        deltas = []
        with patch(
            "assistant.llm.providers.openai_compatible.urlopen",
            return_value=response,
        ):
            message = create_chat_completion(
                self.config,
                [{"role": "user", "content": "test"}],
                [{"type": "function", "function": {"name": "search_messages"}}],
                on_text_delta=deltas.append,
            )

        self.assertEqual(deltas, ["查询", "中"])
        self.assertEqual(message["content"], "查询中")
        self.assertEqual(message["tool_calls"][0]["function"], {
            "name": "search_messages",
            "arguments": '{"service_id":"0x0A01"}',
        })
        self.assertEqual(message["_usage"]["total_tokens"], 12)


if __name__ == "__main__":
    unittest.main()
