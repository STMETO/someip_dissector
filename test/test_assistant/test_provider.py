"""模型 Provider 的 HTTP 请求构造和异常转换测试。"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from assistant.config import ModelConfig
from assistant.provider import ModelProviderError, create_chat_completion


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


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.config = ModelConfig(
            api_key="test-key",
            api_base="https://api.deepseek.com",
            model="test-model",
            timeout_seconds=5.0,
            source="runtime",
        )

    def test_request_headers_are_ascii_and_response_is_parsed(self):
        """防止排版连字符等 Unicode 字符再次进入 HTTP Header。"""
        response = _Response({
            "choices": [{"message": {"role": "assistant", "content": "ok"}}]
        })
        with patch("assistant.provider.urlopen", return_value=response) as mocked:
            message = create_chat_completion(
                self.config,
                [{"role": "user", "content": "你好"}],
                [],
            )

        request = mocked.call_args.args[0]
        for name, value in request.header_items():
            name.encode("ascii")
            value.encode("ascii")
        self.assertEqual(request.get_header("User-agent"), "someip-dissector-assistant/1.0")
        self.assertEqual(message["content"], "ok")

    def test_header_encoding_error_becomes_provider_error(self):
        """底层编码错误必须转换成可由 FastAPI 返回的业务异常。"""
        encoding_error = UnicodeEncodeError("ascii", "密钥", 0, 1, "not ascii")
        with patch("assistant.provider.urlopen", side_effect=encoding_error):
            with self.assertRaisesRegex(ModelProviderError, "HTTP Header"):
                create_chat_completion(
                    self.config,
                    [{"role": "user", "content": "test"}],
                    [],
                )


if __name__ == "__main__":
    unittest.main()
