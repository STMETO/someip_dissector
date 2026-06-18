from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from secrets import token_urlsafe

from fastapi import UploadFile


@dataclass(slots=True)
class SessionWorkspace:
    session_id: str
    root: Path
    upload_dir: Path
    export_dir: Path


class SessionManager:
    def __init__(self, base_dir: Path | None = None, ttl_hours: int = 12) -> None:
        if base_dir is None:
            base_dir = Path(tempfile.gettempdir()) / "someip_dissector_web"
        self.base_dir = base_dir
        self.ttl = timedelta(hours=ttl_hours)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self) -> SessionWorkspace:
        session_id = token_urlsafe(9)
        root = self.base_dir / session_id
        upload_dir = root / "uploads"
        export_dir = root / "exports"
        upload_dir.mkdir(parents=True, exist_ok=True)
        export_dir.mkdir(parents=True, exist_ok=True)
        return SessionWorkspace(
            session_id=session_id,
            root=root,
            upload_dir=upload_dir,
            export_dir=export_dir,
        )

    async def persist_upload(
        self,
        workspace: SessionWorkspace,
        upload: UploadFile,
        *,
        stem: str,
    ) -> Path:
        suffix = Path(upload.filename or "").suffix.lower()
        destination = workspace.upload_dir / f"{stem}{suffix}"
        with destination.open("wb") as file_obj:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                file_obj.write(chunk)
        await upload.close()
        return destination

    def resolve_export(self, session_id: str, filename: str) -> Path | None:
        candidate = (self.base_dir / session_id / "exports" / filename).resolve()
        export_root = (self.base_dir / session_id / "exports").resolve()
        if not candidate.is_file():
            return None
        if export_root not in candidate.parents:
            return None
        return candidate

    def cleanup_expired(self) -> int:
        removed = 0
        now = datetime.now(timezone.utc)
        for child in self.base_dir.iterdir():
            if not child.is_dir():
                continue
            modified = datetime.fromtimestamp(child.stat().st_mtime, tz=timezone.utc)
            if now - modified > self.ttl:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        return removed
