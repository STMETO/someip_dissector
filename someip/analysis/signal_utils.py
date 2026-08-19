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

def find_field_node(node: dict, path_parts: list[str]) -> dict[str, Any] | None:
    """按字段路径查找节点，同时支持包含或省略根节点名称的路径。

    信号页面生成的路径不包含根节点名称；模型有时会根据解析树传入完整路径，
    因此这里兼容两种形式。数组路径未指定下标时匹配首个同名元素，显式写出
    ``items[2]`` 时则只匹配该元素。
    """
    parts = [part.strip() for part in path_parts if part.strip()]
    if not parts:
        return None

    if _name_matches(node.get("name", ""), parts[0]):
        matched = _match_node(node, parts, 0)
        if matched is not None:
            return matched

        # ARXML 数组根节点和数组元素常具有相同的基础名称，例如：
        #   ADAS_arr_DynamicObjects_2
        #     ADAS_arr_DynamicObjects_2[0]
        # 元数据为了生成稳定曲线会去掉 ``[0]``，形成
        # ``ADAS_arr_DynamicObjects_2.objectId``。此时根节点虽然匹配首段，
        # 下一段却位于数组元素内部，需要继续从子节点尝试同一路径。
    for child in node.get("children", []):
        result = _match_node(child, parts, 0)
        if result is not None:
            return result
    return None


def get_field_value(node: dict, path_parts: list[str]) -> float | int | None:
    """按路径提取叶子节点数值，非数值字段返回 ``None``。"""
    matched = find_field_node(node, path_parts)
    return _to_number(matched.get("value")) if matched is not None else None


def _match_node(node: dict, parts: list[str], idx: int) -> dict[str, Any] | None:
    """递归匹配路径段并返回目标节点，不复制其子树。"""
    if idx >= len(parts):
        return None
    if not _name_matches(node.get("name", ""), parts[idx]):
        return None

    if idx == len(parts) - 1:
        return node

    for child in node.get("children", []):
        result = _match_node(child, parts, idx + 1)
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
                "timestamp_epoch": curr.get("timestamp_epoch", 0.0),
                "timestamp_iso": curr.get("timestamp_iso", ""),
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
    """比较路径段；目标显式包含数组下标时执行精确匹配。"""
    node_name = str(node_name).strip()
    target = str(target).strip()
    if "[" in target:
        return node_name == target
    return _strip_index(node_name) == target


def _to_number(val: Any) -> float | int | None:
    """将值转为数值类型，不可转为数值的返回 None。"""
    if val is None:
        return None
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, (int, float)):
        return val
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
