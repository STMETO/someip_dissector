"""
SD 订阅诊断 API — Web 胶水层。

从会话缓存取 messages + registry → 调 analysis 模块生成诊断报告 → 返回 JSON。
"""
from __future__ import annotations
from typing import Any

from analysis.sd_diagnostic import build_subscription_report
from web.backend.handlers.analysis import get_session


def get_subscription_report(session_id: str) -> dict[str, Any] | None:
    """返回订阅诊断报告。"""
    state = get_session(session_id)
    if state is None:
        return None

    registry = getattr(state, "registry", None)
    return build_subscription_report(state.messages, registry)
