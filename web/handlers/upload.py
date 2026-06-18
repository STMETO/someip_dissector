from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from web.utils.session import SessionManager, SessionWorkspace

_PCAP_SUFFIXES = {".pcap", ".pcapng", ".cap"}
_ARXML_SUFFIXES = {".arxml", ".xml"}


class InvalidUploadError(ValueError):
    """Raised when upload fields are missing or invalid."""


@dataclass(slots=True)
class UploadBundle:
    workspace: SessionWorkspace
    pcap_path: Path
    arxml_path: Path


async def save_upload_bundle(
    session_manager: SessionManager,
    pcap_file: UploadFile,
    arxml_file: UploadFile,
) -> UploadBundle:
    _validate_upload(pcap_file, _PCAP_SUFFIXES, "pcap")
    _validate_upload(arxml_file, _ARXML_SUFFIXES, "arxml")

    workspace = session_manager.create_session()
    pcap_path = await session_manager.persist_upload(workspace, pcap_file, stem="capture")
    arxml_path = await session_manager.persist_upload(workspace, arxml_file, stem="schema")
    return UploadBundle(workspace=workspace, pcap_path=pcap_path, arxml_path=arxml_path)


def _validate_upload(upload: UploadFile | None, suffixes: set[str], label: str) -> None:
    if upload is None or not upload.filename:
        raise InvalidUploadError(f"缺少 {label} 文件")
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in suffixes:
        allowed = ", ".join(sorted(suffixes))
        raise InvalidUploadError(f"{label} 文件类型不正确，允许: {allowed}")
