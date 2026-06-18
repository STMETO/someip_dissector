"""上传文件保存与校验。"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

_TEMP_ROOT = Path(__file__).resolve().parent.parent.parent / "sessions"
_PCAP_EXTS = {".pcap", ".pcapng", ".cap"}
_ARXML_EXTS = {".arxml", ".xml"}


def create_session_dir(session_id: str) -> Path:
    path = _TEMP_ROOT / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


async def save_upload(upload: UploadFile, session_dir: Path, stem: str) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    destination = session_dir / f"{stem}{suffix}"
    with destination.open("wb") as f:
        while chunk := await upload.read(1024 * 1024):
            f.write(chunk)
    await upload.close()
    return destination


async def validate_and_save(
    pcap_file: UploadFile,
    arxml_file: UploadFile,
    keep_temp: bool = False,
) -> tuple[Path, Path, str]:
    _check_ext(pcap_file, _PCAP_EXTS, "pcap")
    _check_ext(arxml_file, _ARXML_EXTS, "arxml")

    session_id = uuid.uuid4().hex[:12]
    session_dir = create_session_dir(session_id)

    pcap_path = await save_upload(pcap_file, session_dir, "capture")
    arxml_path = await save_upload(arxml_file, session_dir, "schema")

    return pcap_path, arxml_path, session_id


def cleanup_session(session_id: str) -> None:
    path = _TEMP_ROOT / session_id
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _check_ext(upload: UploadFile, allowed: set[str], label: str) -> None:
    if not upload.filename:
        raise ValueError(f"缺少 {label} 文件")
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in allowed:
        raise ValueError(f"{label} 文件类型不正确，允许: {', '.join(sorted(allowed))}")
