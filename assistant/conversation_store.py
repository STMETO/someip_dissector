"""AI 对话的可选磁盘持久化存储。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_STORE_DIR = "assistant"
_STORE_FILE = "conversations.json"
_STORE_VERSION = 1


def load_conversations(session_dir: Path) -> dict[str, Any] | None:
    """读取并做最小结构校验；损坏文件不会阻止解析记录正常打开。"""
    path = _store_path(session_dir)
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("version") != _STORE_VERSION:
        return None
    if not isinstance(payload.get("conversations"), list):
        return None
    return payload


def save_conversations(session_dir: Path, conversations: list[dict[str, Any]]) -> None:
    """使用临时文件原子替换，避免进程中断后留下半份 JSON。"""
    store_dir = session_dir / _STORE_DIR
    store_dir.mkdir(parents=True, exist_ok=True)
    target = store_dir / _STORE_FILE
    temporary = store_dir / f".{_STORE_FILE}.tmp"
    payload = {
        "version": _STORE_VERSION,
        "enabled": True,
        "conversations": conversations,
    }
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
    temporary.replace(target)


def remove_conversations(session_dir: Path) -> None:
    """关闭对话持久化时只删除 AI 文件，不影响 PCAP/ARXML 解析产物。"""
    store_dir = session_dir / _STORE_DIR
    path = store_dir / _STORE_FILE
    if path.exists():
        path.unlink()
    temporary = store_dir / f".{_STORE_FILE}.tmp"
    if temporary.exists():
        temporary.unlink()
    try:
        store_dir.rmdir()
    except OSError:
        # 目录非空或已被并发删除时无需影响主流程。
        pass


def has_conversations(session_dir: Path) -> bool:
    return _store_path(session_dir).is_file()


def _store_path(session_dir: Path) -> Path:
    return session_dir / _STORE_DIR / _STORE_FILE


__all__ = [
    "has_conversations",
    "load_conversations",
    "remove_conversations",
    "save_conversations",
]
