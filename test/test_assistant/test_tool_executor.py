"""Tool 执行预算、超时、取消和结果限制测试。"""
from __future__ import annotations

import json
from threading import Event
import time
import unittest
from unittest.mock import Mock

from assistant.execution.run_record import AssistantRunRecord
from assistant.execution.tool_executor import (
    ToolExecutionBudget,
    ToolExecutionCancelled,
    ToolExecutor,
)


class ToolExecutorTests(unittest.TestCase):
    def test_invalid_arguments_are_rejected_before_handler(self):
        handler = Mock(return_value={"events": []})
        executor = self._executor(handler)

        outcome = executor.execute("get_offer_timeline", "{}")

        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "invalid_arguments")
        self.assertIn("service_id", outcome.content)
        handler.assert_not_called()

    def test_unknown_arguments_are_rejected(self):
        handler = Mock(return_value={"messages": []})
        executor = self._executor(handler)

        outcome = executor.execute("search_messages", '{"shell":"id"}')

        self.assertEqual(outcome.error_code, "invalid_arguments")
        handler.assert_not_called()

    def test_timeout_becomes_partial_failure_without_blocking_request(self):
        def slow_handler(_name, _arguments, _session_id):
            time.sleep(0.2)
            return {"messages": []}

        executor = self._executor(
            slow_handler,
            ToolExecutionBudget(
                single_tool_timeout_seconds=0.03,
                cumulative_tool_seconds=0.1,
            ),
        )
        started = time.monotonic()

        outcome = executor.execute("search_messages", "{}")

        self.assertLess(time.monotonic() - started, 0.15)
        self.assertEqual(outcome.error_code, "tool_timeout")
        self.assertEqual(outcome.status, "failed")

    def test_cancel_interrupts_waiting_for_tool(self):
        def slow_handler(_name, _arguments, _session_id):
            time.sleep(0.2)
            return {"messages": []}

        cancel_event = Event()
        cancel_event.set()
        executor = self._executor(slow_handler)

        with self.assertRaises(ToolExecutionCancelled):
            executor.execute("search_messages", "{}", cancel_event)
        self.assertEqual(executor.run_record.tool_calls[0].status, "cancelled")

    def test_oversized_result_keeps_verified_partial_evidence(self):
        def large_handler(_name, _arguments, _session_id):
            return {
                "messages": [{"message_index": 7, "frame_index": 107}],
                "payload": "ab" * 1000,
            }

        executor = self._executor(
            large_handler,
            ToolExecutionBudget(
                max_result_bytes=300,
                max_total_result_bytes=1000,
            ),
        )

        outcome = executor.execute("search_messages", "{}")
        content = json.loads(outcome.content)

        self.assertEqual(outcome.status, "partial")
        self.assertEqual(outcome.error_code, "tool_result_budget_exceeded")
        self.assertTrue(content["partial"])
        self.assertEqual(content["evidence"][0]["message_index"], 7)
        self.assertNotIn("abababab", outcome.content)

    def test_call_budget_prevents_additional_handler_execution(self):
        handler = Mock(return_value={"messages": []})
        executor = self._executor(
            handler,
            ToolExecutionBudget(max_tool_calls=1),
        )

        first = executor.execute("search_messages", "{}")
        second = executor.execute("search_messages", "{}")

        self.assertTrue(first.ok)
        self.assertEqual(second.error_code, "tool_call_budget_exceeded")
        self.assertEqual(handler.call_count, 1)

    def test_unserializable_result_is_converted_to_safe_error(self):
        executor = self._executor(lambda *_args: {"bad": object()})

        outcome = executor.execute("search_messages", "{}")

        self.assertEqual(outcome.error_code, "invalid_tool_result")
        self.assertNotIn("object at", outcome.content)

    @staticmethod
    def _executor(handler, budget=None):
        record = AssistantRunRecord(
            request_id="request-1",
            session_id="session-1",
            model="test-model",
            prompt_version="test-prompt",
            answer_contract_version="test-contract",
        )
        return ToolExecutor(
            "session-1",
            record,
            budget=budget or ToolExecutionBudget(),
            tool_handler=handler,
        )


if __name__ == "__main__":
    unittest.main()
