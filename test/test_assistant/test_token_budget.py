"""Token 预算和滚动摘要测试。"""
from __future__ import annotations

import unittest

from assistant.conversation.context_budget import (
    ContextBudgetError,
    build_context_plan,
    estimate_request_tokens,
)


class TokenBudgetTests(unittest.TestCase):
    def test_old_turns_are_summarized_and_recent_turns_are_retained(self):
        history = []
        for index in range(12):
            history.extend([
                {"role": "user", "content": f"问题 {index} " + "x" * 180},
                {"role": "assistant", "content": f"回答 {index} " + "y" * 240},
            ])

        plan = build_context_plan(
            system_prompt="SOME/IP 助手",
            history=history,
            summary="",
            question="继续分析",
            tools=[],
            model="unknown-model",
            context_window=1800,
            max_output_tokens=128,
        )

        self.assertGreater(plan.dropped_messages, 0)
        self.assertLess(len(plan.retained_history), len(history))
        self.assertIn("用户：", plan.summary)
        self.assertEqual(plan.retained_history[-2]["content"], history[-2]["content"])
        self.assertLess(plan.estimated_input_tokens, plan.context_window)

    def test_base_prompt_over_budget_is_rejected(self):
        with self.assertRaises(ContextBudgetError):
            build_context_plan(
                system_prompt="中" * 1000,
                history=[],
                summary="",
                question="问题",
                tools=[],
                model="unknown-model",
                context_window=700,
                max_output_tokens=128,
            )

    def test_full_request_estimate_includes_tool_result(self):
        base = estimate_request_tokens(
            [{"role": "user", "content": "查询"}],
            [],
            "unknown-model",
        )
        with_tool_result = estimate_request_tokens(
            [
                {"role": "user", "content": "查询"},
                {"role": "tool", "content": "x" * 4000},
            ],
            [],
            "unknown-model",
        )

        self.assertGreater(with_tool_result, base + 500)


if __name__ == "__main__":
    unittest.main()
