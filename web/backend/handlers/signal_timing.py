"""信号时序 Web 接口，只负责会话读取和参数适配。"""
from __future__ import annotations
from typing import Any

from analysis.queries import ensure_session_queries
from web.backend.handlers.analysis import get_session


# ═══════════════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════════════

def get_signal_meta(session_id: str) -> list[dict[str, Any]]:
    """返回会话中可绘制信号的三级级联数据（服务→事件→字段路径）。"""
    state = get_session(session_id)
    if state is None:
        return []

    return ensure_session_queries(state).signals.metadata()


def get_signal_data(
    session_id: str,
    service_id: int,
    event_id: int,
    field_path: str,
) -> dict[str, Any] | None:
    """从会话缓存中提取指定字段的时序数据 + 跳变点。"""
    state = get_session(session_id)
    if state is None:
        return None

    # 前端用逗号传递多选字段，在 Web 边界统一拆分。
    field_paths = [fp.strip() for fp in field_path.split(",") if fp.strip()]
    if not field_paths:
        return None

    return ensure_session_queries(state).signals.field_series(
        service_id,
        event_id,
        field_paths,
    )
