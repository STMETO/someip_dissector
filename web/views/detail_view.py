"""解析树 UI：递归渲染 FieldNode 树为可折叠面板。"""

from __future__ import annotations

from typing import Any

from pywebio.output import put_collapse, put_code, put_text, use_scope


def render_field_tree(tree: dict[str, Any]) -> None:
    """渲染一棵 FieldNode 树。

    Parameters
    ----------
    tree: FieldNode.to_dict() 产物。
    """
    with use_scope("detail", clear=True):
        _render_node(tree, level=0)


def _render_node(node: dict[str, Any], level: int) -> None:
    name = node.get("name", "?")
    type_name = node.get("type", "?")
    offset = node.get("offset", 0)
    byte_size = node.get("byte_size", 0)
    hex_str = node.get("hex", "")
    value = node.get("value")
    children = node.get("children", [])

    # 构建标题
    title_parts = [f"{name}  ({type_name}, {byte_size}B @{offset})"]
    if value is not None:
        title_parts.append(f" = {value}")

    if children:
        # 容器节点：折叠面板
        items = []
        for child in children:
            items.append(_build_child_item(child))
        put_collapse(" | ".join(title_parts), items)
    else:
        # 叶节点：显示十六进制和值
        content = [f"{'  ' * level} {' | '.join(title_parts)}"]
        if hex_str:
            content.append(f"{'  ' * (level + 1)}hex: {hex_str}")
        put_text("\n".join(content))


def _build_child_item(child: dict[str, Any]) -> Any:
    """递归构建折叠面板的子项。"""
    name = child.get("name", "?")
    type_name = child.get("type", "?")
    offset = child.get("offset", 0)
    byte_size = child.get("byte_size", 0)
    hex_str = child.get("hex", "")
    value = child.get("value")
    children = child.get("children", [])

    title_parts = [f"{name}  ({type_name}, {byte_size}B @{offset})"]
    if value is not None:
        title_parts.append(f" = {value}")

    if children:
        return (
            " | ".join(title_parts),
            [_build_child_item(c) for c in children],
        )
    else:
        parts = [" | ".join(title_parts)]
        if hex_str:
            parts.append(f"    hex: {hex_str}")
        return "\n".join(parts)
