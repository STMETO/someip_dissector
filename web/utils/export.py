"""导出工具：为中间 JSON 产物生成下载链接。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pywebio.output import put_link


def make_download_links(session_dir: Path, results: list[dict[str, Any]]) -> None:
    """保存完整反序列化结果为 JSON 并展示下载链接。"""
    filepath = session_dir / "deserialized_full.json"
    with filepath.open("w", encoding="utf-8") as f:
        json.dump({"results": results}, f, ensure_ascii=False, indent=2)

    put_link("下载完整解析结果 (JSON)", str(filepath))
