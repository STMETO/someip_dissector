"""对话 Token 估算、上下文预算和滚动摘要。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable


class ContextBudgetError(RuntimeError):
    """系统提示和当前问题本身已经超过可用上下文。"""


@dataclass(frozen=True)
class ContextPlan:
    """一次请求最终采用的上下文及预算统计。"""

    messages: list[dict[str, Any]]
    retained_history: list[dict[str, str]]
    summary: str
    dropped_messages: int
    estimated_input_tokens: int
    context_window: int
    tokenizer: str


def build_context_plan(
    *,
    system_prompt: str,
    history: list[dict[str, str]],
    summary: str,
    question: str,
    tools: list[dict[str, Any]],
    model: str,
    context_window: int,
    max_output_tokens: int,
) -> ContextPlan:
    """优先保留最近完整对话轮次，较旧内容并入有界滚动摘要。"""
    count, tokenizer = _counter(model)
    tool_tokens = count(json.dumps(tools, ensure_ascii=False, separators=(",", ":")))
    # 除最大输出外再保留协议和供应商差异余量，防止估算值刚好顶满窗口。
    input_limit = context_window - max_output_tokens - tool_tokens - 512
    if input_limit < 512:
        raise ContextBudgetError("上下文窗口不足以容纳 Tool Schema 和最大输出预算")

    turns = _to_turns(history)
    kept_turns: list[list[dict[str, str]]] = []
    dropped_turns: list[list[dict[str, str]]] = []
    base = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]
    if _count_messages(base, count) > input_limit:
        raise ContextBudgetError("系统提示和当前问题超过模型上下文预算")

    # 从最近一轮向前装入，保证不会只保留 assistant 而丢掉对应 user。
    dropping_older = False
    for turn in reversed(turns):
        if dropping_older:
            dropped_turns.insert(0, turn)
            continue
        candidate_turns = [turn, *kept_turns]
        candidate = _compose_messages(system_prompt, summary, candidate_turns, question)
        if _count_messages(candidate, count) <= input_limit:
            kept_turns = candidate_turns
        else:
            dropped_turns.insert(0, turn)
            dropping_older = True

    next_summary = _extend_summary(summary, dropped_turns)
    messages = _compose_messages(system_prompt, next_summary, kept_turns, question)
    # 摘要也可能增长到超过预算，从较旧一侧裁剪并保留提示标签。
    # 如果最近历史已经占满窗口，摘要可能被压缩为空；此时把最旧的一轮已保留
    # 对话移入摘要，为有意义的摘要腾出空间。tiktoken 与保守估算器都必须满足
    # “发生历史裁剪就保留摘要”这一行为契约。
    while next_summary and _count_messages(messages, count) > input_limit:
        trimmed_summary = _trim_summary(next_summary)
        if not trimmed_summary and kept_turns:
            dropped_turns.append(kept_turns.pop(0))
            next_summary = _extend_summary(summary, dropped_turns)
        else:
            next_summary = trimmed_summary
        messages = _compose_messages(system_prompt, next_summary, kept_turns, question)
    if _count_messages(messages, count) > input_limit:
        raise ContextBudgetError("最近对话轮次超过模型上下文预算，请缩短当前问题")

    return ContextPlan(
        messages=messages,
        retained_history=[message for turn in kept_turns for message in turn],
        summary=next_summary,
        dropped_messages=sum(len(turn) for turn in dropped_turns),
        estimated_input_tokens=_count_messages(messages, count) + tool_tokens,
        context_window=context_window,
        tokenizer=tokenizer,
    )


def tokenizer_name(model: str) -> str:
    """返回当前模型会使用的 Token 计数器名称。"""
    return _counter(model)[1]


def estimate_request_tokens(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str,
) -> int:
    """估算完整模型请求，包含流转中的 Tool Call 参数和 Tool 返回内容。"""
    count, _ = _counter(model)
    payload = {"messages": messages, "tools": tools}
    return count(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))) + 16


def _compose_messages(
    system_prompt: str,
    summary: str,
    turns: list[list[dict[str, str]]],
    question: str,
) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": system_prompt}]
    if summary:
        messages.append({
            "role": "system",
            "content": f"较早对话的滚动摘要，仅用于保持上下文：\n{summary}",
        })
    for turn in turns:
        messages.extend(turn)
    messages.append({"role": "user", "content": question})
    return messages


def _to_turns(history: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    turns: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    for message in history:
        if message.get("role") == "user" and current:
            turns.append(current)
            current = []
        if message.get("role") in {"user", "assistant"}:
            current.append({
                "role": message["role"],
                "content": str(message.get("content") or ""),
            })
        if message.get("role") == "assistant" and current:
            turns.append(current)
            current = []
    if current:
        turns.append(current)
    return turns


def _extend_summary(summary: str, turns: list[list[dict[str, str]]]) -> str:
    if not turns:
        return summary
    lines = [summary.strip()] if summary.strip() else []
    for turn in turns:
        user = next((item["content"] for item in turn if item["role"] == "user"), "")
        assistant = next((item["content"] for item in turn if item["role"] == "assistant"), "")
        lines.append(f"用户：{_compact(user, 500)}")
        if assistant:
            lines.append(f"助手：{_compact(assistant, 900)}")
    return "\n".join(lines).strip()


def _compact(value: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized if len(normalized) <= limit else normalized[:limit] + "..."


def _trim_summary(summary: str) -> str:
    lines = summary.splitlines()
    if len(lines) > 2:
        # 摘要以“用户/助手”两行为一轮，从最旧完整轮次开始删除。
        return "\n".join(lines[2:])
    if not lines:
        return ""
    shortened: list[str] = []
    changed = False
    for line in lines:
        prefix, separator, content = line.partition("：")
        if separator and len(content) > 40:
            # 新长度必须严格小于旧长度，保证外层预算循环一定终止。
            next_length = max(20, len(content) * 2 // 3)
            content = content[:next_length] + "..."
            shortened.append(f"{prefix}：{content}")
            changed = True
        else:
            shortened.append(line)
    # 已无法继续有意义地压缩时舍弃摘要，不能留下失去角色标签的字符串碎片。
    return "\n".join(shortened) if changed else ""


def _count_messages(messages: list[dict[str, Any]], count: Callable[[str], int]) -> int:
    # OpenAI 格式每条消息有少量角色与分隔符开销，统一保守增加 5 Token。
    return 3 + sum(5 + count(str(item.get("content") or "")) for item in messages)


@lru_cache(maxsize=32)
def _counter(model: str) -> tuple[Callable[[str], int], str]:
    """优先使用 tiktoken；未安装时采用偏保守的 Unicode 估算器。"""
    try:
        import tiktoken  # type: ignore
        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")
        return lambda text: len(encoding.encode(text)), f"tiktoken:{encoding.name}"
    except ImportError:
        return _fallback_count, "conservative-unicode-estimate"


def _fallback_count(text: str) -> int:
    # 中日韩字符通常接近 1 Token；ASCII 以约 4 字符一个 Token 计算，并向上取整。
    cjk = sum(1 for char in text if "\u2e80" <= char <= "\u9fff")
    other = len(text) - cjk
    return cjk + max(1, (other + 3) // 4)


__all__ = [
    "ContextBudgetError",
    "ContextPlan",
    "build_context_plan",
    "estimate_request_tokens",
    "tokenizer_name",
]
