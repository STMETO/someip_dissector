"""文件上传处理器：接收 pcap 和 arxml，保存到会话临时目录。"""

from __future__ import annotations

from pathlib import Path

from pywebio.input import file_upload
from pywebio.output import put_markdown, put_text, toast

from web.utils.session import SessionManager


def handle_upload(session: SessionManager) -> tuple[Path | None, Path | None]:
    """上传 pcap 和 arxml，返回本地路径。

    用户可拖拽或选择文件，必须同时上传两个文件。
    """
    put_markdown("## 上传文件")

    files = file_upload(
        "请选择 sample.pcap 和 sample.arxml",
        accept=".pcap,.arxml,.xml",
        multiple=True,
        required=True,
        placeholder="拖动文件到此处或点击选择",
    )

    pcap_path = None
    arxml_path = None
    for f in files:
        if f["filename"].lower().endswith((".pcap", ".pcapng")):
            pcap_path = session.save(f["filename"], f["content"])
            put_text(f"✓ PCAP: {f['filename']} ({len(f['content'])} bytes)")
        elif f["filename"].lower().endswith((".arxml", ".xml")):
            arxml_path = session.save(f["filename"], f["content"])
            put_text(f"✓ ARXML: {f['filename']} ({len(f['content'])} bytes)")

    if not pcap_path:
        toast("未上传有效的 pcap 文件", color="error")
        return None, None
    if not arxml_path:
        toast("未上传有效的 arxml 文件", color="error")
        return None, None

    return pcap_path, arxml_path
