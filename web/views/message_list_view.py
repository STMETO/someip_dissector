"""消息列表 UI：以表格形式展示解析消息列表，支持点击回调。"""

from __future__ import annotations

from typing import Any, Callable

from pywebio.output import put_button, put_table, put_text, use_scope
from pywebio.session import run_js


def _msg_type_label(mt: str) -> str:
    m = {
        "0x00": "REQ", "0x01": "REQ_NR",
        "0x02": "NOTIF", "0x80": "RESP", "0x81": "ERR",
    }
    return m.get(mt, mt)


def show_message_list(
    messages: list[dict[str, Any]],
    on_select: Callable[[dict[str, Any]], None],
) -> None:
    """渲染消息列表表格，已解析的行可点击查看详情。

    仅展示前 200 条以避免页面卡顿。
    """
    if not messages:
        put_text("无消息数据。")
        return

    headers = ["#", "Service ID", "Method/Event ID", "Type", "Len", "Status", "Action"]
    display = messages[:200]
    rows = []
    for msg in display:
        h = msg.get("header", {})
        srv = h.get("service_id", {}).get("hex", "?")
        mid = h.get("method_id", {}).get("hex", "?")
        mt = h.get("message_type", {}).get("hex", "0x00")
        payload_len = msg.get("payload_length", 0)
        has_tree = msg.get("tree") is not None

        rows.append([
            str(msg["index"]),
            srv,
            mid,
            _msg_type_label(mt),
            str(payload_len),
            "✓" if has_tree else "✗",
            put_button("查看", onclick=_wrap_handler(msg, on_select), color="primary", small=True)
            if has_tree
            else "",
        ])

    with use_scope("msg_table", clear=True):
        put_table([headers] + rows)
        run_js("window.scrollTo(0, document.body.scrollHeight)")

    if len(messages) > 200:
        put_text(f"... 仅展示前 200 条，共 {len(messages)} 条")


def _wrap_handler(msg: dict[str, Any], on_select: Callable[[dict[str, Any]], None]):
    def handler():
        run_js("window.scrollTo(0, document.body.scrollHeight)")
        on_select(msg)
    return handler
