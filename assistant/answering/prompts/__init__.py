"""版本化 System Prompt 入口。"""

from .v1 import ANSWER_CONTRACT_VERSION, PROMPT_VERSION, render_system_prompt

__all__ = ["ANSWER_CONTRACT_VERSION", "PROMPT_VERSION", "render_system_prompt"]
