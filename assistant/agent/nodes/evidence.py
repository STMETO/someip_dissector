"""从 ToolMessage artifact 收集独立证据和执行轨迹。"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import ToolMessage

from ..routing import AgentRoute
from ..state import SomeIpAgentState
from .support import latest_ai_text


def collect_evidence_node(state: SomeIpAgentState) -> dict[str, Any]:
    """提取有限证据，确定成功、部分失败、失败或取消路由。"""
    # 补充查询再次进入该节点时累加既有证据，不能覆盖第一轮事实。
    traces: list[dict[str, Any]] = list(state.get("tool_trace", []))
    evidence: list[dict[str, Any]] = list(state.get("evidence", []))
    navigation_links: list[dict[str, Any]] = list(state.get("navigation_links", []))
    warnings = list(state.get("warnings", []))
    statuses: list[str] = [str(item.get("status") or "") for item in traces]
    error_codes: list[str] = [
        str(item.get("error_code"))
        for item in traces
        if item.get("error_code")
    ]

    for message in state.get("react_messages", []):
        if not isinstance(message, ToolMessage):
            continue
        artifact = message.artifact if isinstance(message.artifact, dict) else {}
        execution = artifact.get("execution", {})
        if not isinstance(execution, dict):
            execution = {}
        status = str(execution.get("status") or message.status or "unknown")
        error = artifact.get("error") if isinstance(artifact.get("error"), dict) else {}
        empty_result = _is_empty_result(artifact.get("result"))
        error_code = str(execution.get("error_code") or error.get("code") or "")
        statuses.append(status)
        if error_code:
            error_codes.append(error_code)
        traces.append({
            "sequence": len(traces) + 1,
            "name": message.name or artifact.get("tool") or "unknown",
            "arguments": artifact.get("arguments", {}),
            "status": status,
            "error_code": error_code or None,
            "duration_ms": execution.get("duration_ms", 0),
            "result_bytes": execution.get("result_bytes", 0),
            "truncated": bool(artifact.get("truncated")),
            "empty_result": empty_result,
        })
        evidence.extend(_dict_rows(artifact.get("evidence")))
        navigation_links.extend(_dict_rows(artifact.get("navigation_links")))
        warnings.extend(str(value) for value in artifact.get("warnings", []) if value)
        if empty_result:
            warnings.append(
                f"Tool {message.name or artifact.get('tool') or 'unknown'} 未找到匹配数据。"
            )

    route = _evidence_route(statuses, error_codes, state.get("route"))
    if (
        route == AgentRoute.FAILED
        and traces
        and latest_ai_text(state.get("react_messages", []))
    ):
        # 模型已经基于失败信封完成回答时保留为部分结果，回答节点会强制追加
        # “查询限制”；这比丢弃已返回的错误证据并返回泛化 500 更可诊断。
        route = AgentRoute.PARTIAL_FAILURE
    if not traces and route == AgentRoute.FAILED:
        warnings.append("ReAct 子图没有产生可验证的 Tool 结果。")
    return {
        "tool_trace": traces,
        "evidence": _deduplicate(evidence),
        "navigation_links": _deduplicate(navigation_links),
        "warnings": list(dict.fromkeys(warnings)),
        "route": route.value,
        "status": "evidence_collected",
    }


def _evidence_route(
    statuses: list[str],
    error_codes: list[str],
    previous_route: str | None,
) -> AgentRoute:
    if previous_route == AgentRoute.CANCELLED.value or "cancelled" in error_codes:
        return AgentRoute.CANCELLED
    if not statuses:
        return AgentRoute.FAILED
    succeeded = any(value == "success" for value in statuses)
    partial = any(value == "partial" for value in statuses)
    failed = any(value in {"failed", "error"} for value in statuses)
    if (succeeded or partial) and (failed or partial):
        return AgentRoute.PARTIAL_FAILURE
    if failed and not succeeded:
        return AgentRoute.FAILED
    return AgentRoute.FINISH


def _dict_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _is_empty_result(value: Any) -> bool:
    """识别查询成功但无匹配项；空结果是事实，不应被当作执行失败。"""
    if not isinstance(value, dict) or value.get("error"):
        return False
    count_keys = [
        key
        for key in value
        if key.endswith("_count") and key.startswith(("matched_", "returned_"))
    ]
    if count_keys and all(value.get(key) == 0 for key in count_keys):
        return True
    collection_keys = (
        "anomalies",
        "events",
        "messages",
        "rows",
        "services",
        "traces",
        "values",
    )
    present = [value.get(key) for key in collection_keys if key in value]
    return bool(present) and all(item == [] for item in present)


def _deduplicate(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按稳定 JSON 去重，保持 Tool 首次返回的证据顺序。"""
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        try:
            key = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            continue
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


__all__ = ["collect_evidence_node"]
