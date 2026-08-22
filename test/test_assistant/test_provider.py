"""LangChain ChatModel Provider 目录与能力探测测试。"""
from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage

from assistant.integrations.langchain import (
    ModelRequestError,
    probe_chat_model,
    provider_catalog,
)
from assistant.llm.config import ModelConfig
from test.test_assistant.fakes import FailingChatModel, ScriptedChatModel


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.config = ModelConfig(
            api_key="test-key",
            api_base="https://api.deepseek.com",
            model="deepseek-chat",
            timeout_seconds=5.0,
            source="runtime",
            provider="deepseek",
            stream=False,
        )

    def test_provider_catalog_is_backed_by_langchain_adapters(self):
        rows = provider_catalog()

        self.assertEqual(
            {row["provider"] for row in rows},
            {"auto", "deepseek", "openai_compatible"},
        )
        self.assertTrue(all(row["supports_tools"] for row in rows))

    @patch("assistant.integrations.langchain.models.create_chat_model")
    def test_probe_uses_standard_tool_call(self, mocked_create):
        mocked_create.return_value = ScriptedChatModel(responses=[AIMessage(
            content="",
            tool_calls=[{
                "name": "_assistant_capability_probe",
                "args": {"value": 1},
                "id": "probe-1",
                "type": "tool_call",
            }],
        )])

        result = probe_chat_model(self.config)

        self.assertTrue(result["ok"])
        self.assertTrue(result["supports_tools"])
        self.assertFalse(result["supports_stream"])
        mocked_create.assert_called_once_with(self.config, require_tools=True)

    @patch("assistant.integrations.langchain.models.create_chat_model")
    def test_probe_error_does_not_expose_api_key(self, mocked_create):
        secret_config = replace(self.config, api_key="very-secret-key")
        mocked_create.return_value = FailingChatModel(responses=[])

        with self.assertRaises(ModelRequestError) as raised:
            probe_chat_model(secret_config)

        self.assertNotIn(secret_config.api_key, str(raised.exception))
        self.assertIn("模型能力探测失败", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
