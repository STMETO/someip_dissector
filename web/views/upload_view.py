"""上传页面 UI：展示信息、接收文件、触发解析。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pywebio.output import (
    put_markdown,
    put_row,
    put_button,
    put_loading,
    put_text,
    toast,
)
from pywebio.session import run_js

from web.handlers import handle_upload, run_analysis_pipeline
from web.utils.session import SessionManager
from web.views.message_list_view import show_message_list
from web.views.detail_view import render_field_tree


def show_upload_page(session: SessionManager) -> None:
    """渲染上传页面并在解析完成后跳转到结果页。"""
    put_markdown("# SOME/IP Dissector")
    put_text("上传 pcap 和 arxml 文件，自动完成全链路解析并在浏览器中查看结果。")

    pcap, arxml = handle_upload(session)
    if pcap is None or arxml is None:
        return

    # 执行解析
    with put_loading():
        messages, type_pool_info, registry_info = run_analysis_pipeline(pcap, arxml)

    # 统计
    parsed = sum(1 for m in messages if m.get("tree") is not None)
    put_text(f"解析完成: {parsed} / {len(messages)} 条消息可反序列化 "
             f"({100 * parsed / len(messages):.1f}%)")

    # 跳转结果页
    run_js("window.scrollTo(0, document.body.scrollHeight)")
    _show_results(messages, type_pool_info, registry_info, session)


def _show_results(
    messages: list[dict[str, Any]],
    type_pool_info: dict[str, Any],
    registry_info: dict[str, Any],
    session: SessionManager,
) -> None:
    """渲染结果页面：左侧消息列表 + 右侧详情。"""
    put_row([
        put_markdown(f"## 消息列表 ({len(messages)} 条)"),
        put_button("导出 JSON", onclick=lambda: _export_results(session, messages)),
    ])

    show_message_list(messages, on_select=lambda msg: _show_detail(msg))


def _show_detail(msg: dict[str, Any]) -> None:
    """用户点击某条消息时展示解析树。"""
    tree = msg.get("tree")
    if tree is None:
        put_text("该消息未能反序列化（类型未注册或数据异常）。")
        return
    render_field_tree(tree)


def _export_results(session: SessionManager, messages: list[dict[str, Any]]) -> None:
    """导出完整结果 JSON 并弹出下载链接。"""
    from web.utils.export import make_download_links
    make_download_links(session.dir, messages)
    toast("JSON 已生成", color="success")
