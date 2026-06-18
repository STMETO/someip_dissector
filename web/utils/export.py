from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from web.utils.session import SessionWorkspace


def save_analysis_export(workspace: SessionWorkspace, payload: dict[str, Any]) -> Path:
    export_path = workspace.export_dir / "analysis_result.json"
    with export_path.open("w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, ensure_ascii=False, indent=2)
    return export_path
