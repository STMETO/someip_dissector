"""
信号提取与跳变检测 — 纯后端逻辑，不依赖 web / session。

对已反序列化的 FieldNode 树进行遍历、字段值提取、跳变点检测。
可被 web handler 或 CLI 直接调用。
"""
from __future__ import annotations
from typing import Any


# ═══════════════════════════════════════════════════════════════════
# 字段路径收集
# ═══════════════════════════════════════════════════════════════════

def collect_leaf_paths(node: dict, prefix: str = "") -> list[str]:
    """递归收集 parsed 树中所有叶子字段的 . 分隔路径（去重，去掉数组下标）。

    路径用类型名而非实例名：ADAS_arr[0].field → ADAS_arr.field
    """
    paths: list[str] = []
    kind = node.get("kind", "leaf")

    if kind == "container":
        seen: set[str] = set()
        for child in node.get("children", []):
            cname = _strip_index(child.get("name", ""))
            if not cname or cname in seen:
                continue
            seen.add(cname)
            child_prefix = f"{prefix}.{cname}" if prefix else cname
            paths.extend(collect_leaf_paths(child, child_prefix))
    else:
        if prefix and "value" in node and node["value"] is not None:
            paths.append(prefix)

    return paths


# ═══════════════════════════════════════════════════════════════════
# 字段值提取
# ═══════════════════════════════════════════════════════════════════

def get_field_value(node: dict, path_parts: list[str]) -> float | int | None:
    """按 . 分隔路径逐层查找，返回叶子节点数值。从 children 开始匹配第一段。"""
    if not path_parts:
        return None

    for child in node.get("children", []):
        result = _match_path(child, path_parts, 0)
        if result is not None:
            return result
    return None


def _match_path(node: dict, parts: list[str], idx: int) -> float | int | None:
    """递归匹配路径段。"""
    if idx >= len(parts):
        return None
    if not _name_matches(node.get("name", ""), parts[idx]):
        return None

    if idx == len(parts) - 1:
        val = node.get("value")
        if val is not None:
            return _to_number(val)
        return None

    for child in node.get("children", []):
        result = _match_path(child, parts, idx + 1)
        if result is not None:
            return result

    return None


# ═══════════════════════════════════════════════════════════════════
# 跳变检测
# ═══════════════════════════════════════════════════════════════════

def detect_transitions(
    points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """检测相邻报文间的值跳变。

    每个 point 需含 seq / frame_index / value。
    """
    transitions: list[dict[str, Any]] = []
    for i in range(1, len(points)):
        prev = points[i - 1]
        curr = points[i]
        old_val = prev["value"]
        new_val = curr["value"]

        if _has_changed(old_val, new_val):
            transitions.append({
                "seq": curr["seq"],
                "frame_index": curr["frame_index"],
                "old_value": old_val,
                "new_value": new_val,
            })

    return transitions


# ═══════════════════════════════════════════════════════════════════
# 内部工具
# ═══════════════════════════════════════════════════════════════════

def _strip_index(name: str) -> str:
    """去掉数组下标后缀：ADAS_arr[0] → ADAS_arr。"""
    return name.split("[")[0].strip()


def _name_matches(node_name: str, target: str) -> bool:
    """节点名与路径段比较（忽略数组下标）。"""
    return _strip_index(node_name) == target


def _to_number(val: Any) -> float | int | None:
    """将值转为数值类型，不可转为数值的返回 None。"""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            pass
    return None


def _has_changed(old: float | int, new: float | int) -> bool:
    """判断两个值是否发生跳变。"""
    if isinstance(old, float) or isinstance(new, float):
        return abs(old - new) > 0.1
    return old != new
