"""固定诊断评测集的读取与完整性校验。"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

_DEFAULT_CASES_PATH = Path(__file__).with_name("cases_v1.json")


@dataclass(frozen=True)
class DiagnosticEvaluationCase:
    """一个可用于模型回归的诊断问题及其事实约束。"""

    case_id: str
    category: str
    question: str
    expected_tools: tuple[str, ...]
    required_facts: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
    allowed_evidence: tuple[str, ...]


def load_evaluation_cases(
    path: str | Path | None = None,
) -> tuple[DiagnosticEvaluationCase, ...]:
    """读取版本化 JSON；字段缺失或重复 case_id 时立即报错。"""
    source = Path(path) if path is not None else _DEFAULT_CASES_PATH
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("version") != "diagnostic-eval-v1":
        raise ValueError("不支持的诊断评测集版本")
    rows = payload.get("cases")
    if not isinstance(rows, list) or not rows:
        raise ValueError("诊断评测集不能为空")

    cases: list[DiagnosticEvaluationCase] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("诊断评测用例必须是 JSON 对象")
        case = _parse_case(row)
        if case.case_id in seen:
            raise ValueError(f"诊断评测 case_id 重复: {case.case_id}")
        seen.add(case.case_id)
        cases.append(case)
    return tuple(cases)


def _parse_case(row: dict[str, Any]) -> DiagnosticEvaluationCase:
    required_text = ("case_id", "category", "question")
    for key in required_text:
        if not isinstance(row.get(key), str) or not row[key].strip():
            raise ValueError(f"诊断评测字段 {key} 不能为空")
    return DiagnosticEvaluationCase(
        case_id=row["case_id"].strip(),
        category=row["category"].strip(),
        question=row["question"].strip(),
        expected_tools=_string_tuple(row, "expected_tools"),
        required_facts=_string_tuple(row, "required_facts"),
        forbidden_claims=_string_tuple(row, "forbidden_claims"),
        allowed_evidence=_string_tuple(row, "allowed_evidence"),
    )


def _string_tuple(row: dict[str, Any], key: str) -> tuple[str, ...]:
    value = row.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"诊断评测字段 {key} 必须是非空数组")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"诊断评测字段 {key} 只能包含非空字符串")
    return tuple(item.strip() for item in value)


__all__ = ["DiagnosticEvaluationCase", "load_evaluation_cases"]
