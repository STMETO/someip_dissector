"""LangChain Tool 的模型摘要与前端 artifact 构建器。"""
from __future__ import annotations

import json
from typing import Any

from ...execution.tool_executor import ToolExecutionOutcome


_MODEL_RESULT_MAX_BYTES = 96 * 1024
_MAX_DEPTH = 8
_MAX_DICT_ITEMS = 64
_MAX_LIST_ITEMS = 50
_MAX_STRING_CHARS = 2048


def build_tool_response(
    outcome: ToolExecutionOutcome,
) -> tuple[str, dict[str, Any]]:
    """构建模型可见的有限结果，以及仅供应用层消费的完整 artifact。

    LangChain 的 ``content_and_artifact`` 会把 content 放入模型上下文，而 artifact
    保留在 ToolMessage 上。完整 Tool 结果因此仍可供证据跳转和审计使用，但不会
    无限制占用模型 Token。
    """
    compact_data, compacted = _compact_json(outcome.result)
    warnings = _collect_warnings(outcome.result)
    if compacted:
        warnings.append(
            "模型可见结果已压缩；如需更多记录，请使用 offset 和 limit 分页查询。"
        )

    envelope: dict[str, Any] = {
        "summary": _build_summary(outcome),
        "data": compact_data,
        "evidence": outcome.verified_links,
        "warnings": _unique_strings(warnings),
        "truncated": bool(
            compacted
            or outcome.status == "partial"
            or outcome.result.get("partial")
            or outcome.result.get("truncated")
        ),
        "error": outcome.result.get("error") if not outcome.ok else None,
    }
    content = _json_text(envelope)
    if len(content.encode("utf-8")) > _MODEL_RESULT_MAX_BYTES:
        # 极端深层 Payload 只向模型提供概览；完整受预算结果仍保留在 artifact。
        envelope["data"] = _top_level_overview(outcome.result)
        envelope["warnings"] = _unique_strings([
            *envelope["warnings"],
            "结果超过模型上下文上限，当前仅提供顶层概览；请缩小条件或分页查询。",
        ])
        envelope["truncated"] = True
        content = _json_text(envelope)

    artifact = {
        "tool": outcome.name,
        "arguments": outcome.arguments,
        "result": outcome.result,
        "summary": envelope["summary"],
        "evidence": outcome.verified_links,
        "navigation_links": outcome.links,
        "warnings": envelope["warnings"],
        "truncated": envelope["truncated"],
        "error": envelope["error"],
        "execution": {
            "status": outcome.status,
            "error_code": outcome.error_code,
            "duration_ms": outcome.duration_ms,
            "result_bytes": outcome.result_bytes,
            "original_result_bytes": outcome.original_result_bytes,
        },
    }
    return content, artifact


def build_tool_error_response(
    tool_name: str,
    code: str,
    message: str,
) -> tuple[str, dict[str, Any]]:
    """把框架级校验或运行时配置错误转换为相同的安全结果协议。"""
    error = {"code": code, "message": message}
    envelope = {
        "summary": "Tool 查询未完成",
        "data": {},
        "evidence": [],
        "warnings": ["请修正参数后重试，不要根据失败结果推断抓包事实。"],
        "truncated": False,
        "error": error,
    }
    artifact = {
        "tool": tool_name,
        "arguments": {},
        "result": {},
        "summary": envelope["summary"],
        "evidence": [],
        "navigation_links": [],
        "warnings": envelope["warnings"],
        "truncated": False,
        "error": error,
        "execution": {"status": "failed", "error_code": code},
    }
    return _json_text(envelope), artifact


def _build_summary(outcome: ToolExecutionOutcome) -> Any:
    """优先复用领域查询摘要，否则提取稳定的顶层计数。"""
    summary = outcome.result.get("summary")
    if summary not in (None, "", {}, []):
        compact, _ = _compact_json(summary)
        return compact
    if not outcome.ok:
        return "Tool 查询未完成"

    counters: dict[str, Any] = {}
    for key, value in outcome.result.items():
        if (
            isinstance(value, (int, float, bool))
            or value is None
        ) and (key.endswith("count") or key in {"offset", "next_offset"}):
            counters[key] = value
    return counters or "Tool 查询完成"


def _collect_warnings(result: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("warning", "warnings", "instruction"):
        value = result.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif value:
            values.append(value)
    return [str(value)[:1000] for value in values if str(value).strip()]


def _compact_json(value: Any, depth: int = 0) -> tuple[Any, bool]:
    """按确定性边界压缩 JSON，不修改原 Tool 返回对象。"""
    if depth >= _MAX_DEPTH and isinstance(value, (dict, list)):
        return {"omitted": "达到模型可见最大嵌套深度"}, True
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        compacted = len(value) > _MAX_DICT_ITEMS
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_DICT_ITEMS:
                break
            output[str(key)], item_compacted = _compact_json(item, depth + 1)
            compacted = compacted or item_compacted
        return output, compacted
    if isinstance(value, list):
        output = []
        compacted = len(value) > _MAX_LIST_ITEMS
        for item in value[:_MAX_LIST_ITEMS]:
            compact_item, item_compacted = _compact_json(item, depth + 1)
            output.append(compact_item)
            compacted = compacted or item_compacted
        return output, compacted
    if isinstance(value, str) and len(value) > _MAX_STRING_CHARS:
        return value[:_MAX_STRING_CHARS] + "...", True
    return value, False


def _top_level_overview(result: dict[str, Any]) -> dict[str, Any]:
    """结果仍过大时仅保留摘要、计数和集合规模。"""
    overview: dict[str, Any] = {}
    for key, value in result.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact, _ = _compact_json(value)
            overview[key] = compact
        elif isinstance(value, (list, dict)):
            overview[f"{key}_item_count"] = len(value)
    return overview


def _unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _json_text(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


__all__ = ["build_tool_error_response", "build_tool_response"]
