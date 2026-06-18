"""会话管理：为每个 Web 会话创建隔离的临时目录。"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

_SESSIONS_ROOT = Path(__file__).resolve().parent.parent / "sessions"


class SessionManager:
    """管理上传文件、中间产物的会话目录。"""

    def __init__(self) -> None:
        self.session_id = uuid.uuid4().hex[:12]
        self.dir = _SESSIONS_ROOT / self.session_id
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, filename: str, content: bytes) -> Path:
        path = self.dir / filename
        path.write_bytes(content)
        return path

    def cleanup(self) -> None:
        if self.dir.exists():
            shutil.rmtree(self.dir, ignore_errors=True)
