"""
SD 订阅诊断 API — Web 胶水层。

从会话缓存读取统一查询对象，页面与 AI Tool 返回同一份诊断事实。
"""
from __future__ import annotations
from typing import Any

from someip.analysis.queries import ensure_session_queries
from web.backend.handlers.analysis import get_session


def get_subscription_report(session_id: str) -> dict[str, Any] | None:
    """返回订阅诊断报告。"""
    state = get_session(session_id)
    if state is None:
        return None

    return ensure_session_queries(state).subscriptions.report()
