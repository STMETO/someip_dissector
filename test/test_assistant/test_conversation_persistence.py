"""AI 对话可选持久化测试。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from assistant.config import ModelConfig
from assistant.service import (
    chat,
    clear_all_conversations,
    clear_conversations,
    conversation_overview,
    set_conversation_persistence,
)


class ConversationPersistenceTests(unittest.TestCase):
    def setUp(self):
        clear_all_conversations()
        self.temp = tempfile.TemporaryDirectory()
        self.state = SimpleNamespace(
            session_id="persist-chat-test",
            session_dir=Path(self.temp.name),
            persistent=True,
            total_messages=1,
            pcap_name="fixture.pcap",
        )
        self.config = ModelConfig(
            api_key="do-not-write-this-key",
            api_base="https://example.invalid",
            model="test-model",
            timeout_seconds=5,
            source="runtime",
            stream=False,
        )

    def tearDown(self):
        clear_all_conversations()
        self.temp.cleanup()

    @patch("assistant.service.create_chat_completion")
    @patch("assistant.service.get_model_config")
    @patch("assistant.service.get_session")
    def test_enabled_conversation_is_saved_and_restored_without_api_key(
        self,
        mocked_session,
        mocked_config,
        mocked_completion,
    ):
        mocked_session.return_value = self.state
        mocked_config.return_value = self.config
        mocked_completion.return_value = {
            "role": "assistant",
            "content": "这是回答。",
        }

        set_conversation_persistence(self.state.session_id, True)
        result = chat(self.state.session_id, "这是问题。")
        path = self.state.session_dir / "assistant" / "conversations.json"
        raw = path.read_text(encoding="utf-8")

        self.assertNotIn(self.config.api_key, raw)
        self.assertIn("这是问题。", raw)
        clear_conversations(self.state.session_id)
        overview = conversation_overview(self.state.session_id)
        self.assertEqual(
            overview["conversation"]["conversation_id"],
            result["conversation_id"],
        )
        self.assertEqual(len(overview["conversation"]["history"]), 2)

        payload = json.loads(raw)
        self.assertEqual(payload["version"], 1)
        self.assertTrue(payload["enabled"])


if __name__ == "__main__":
    unittest.main()
