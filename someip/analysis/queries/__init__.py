"""页面 API 与 AI Tool 共用的会话级只读查询入口。"""
from __future__ import annotations

from typing import Any

from .anomaly_query import AnomalyDetailsQuery
from .arxml_definition_query import ArxmlDefinitionQuery
from .evidence import build_message_evidence, header_int, message_service_ids
from .message_query import MessageQuery, MessageSearchResult
from .offer_query import OfferQuery
from .payload_value_query import PayloadValueQuery
from .request_response_query import RequestResponseQuery
from .sd_query import SdRecordQuery
from .service_query import ServiceQuery
from .session_comparison import SessionComparisonQuery
from .signal_query import SignalQuery
from .subscription_query import SubscriptionQuery
from .topology_query import EcuTopologyQuery


class SessionQueries:
    """为一份完整解析结果建立一次索引，并组合各领域查询对象。"""

    def __init__(
        self,
        messages: list[dict[str, Any]],
        registry: Any = None,
        type_pool: dict[str, Any] | None = None,
    ):
        self.messages = MessageQuery(messages)
        self.sd = SdRecordQuery(messages)
        self.subscriptions = SubscriptionQuery(self.sd, self.messages, registry)
        self.offers = OfferQuery(self.sd, registry)
        self.services = ServiceQuery(self.messages, self.subscriptions, registry)
        self.signals = SignalQuery(self.messages, registry)
        # 第六阶段查询均绑定同一消息索引，Tool 层只负责参数校验和结果压缩。
        self.request_responses = RequestResponseQuery(self.messages, registry)
        self.topology = EcuTopologyQuery(
            self.messages,
            self.sd,
            self.subscriptions,
            registry,
        )
        self.arxml = ArxmlDefinitionQuery(registry, type_pool)
        self.payload_values = PayloadValueQuery(self.messages)
        self.anomalies = AnomalyDetailsQuery(self.subscriptions, self.messages)

    @property
    def index_stats(self) -> dict[str, Any]:
        """汇总消息和 SD 索引规模，便于观察构建结果。"""
        return {
            "messages": self.messages.index_stats,
            "sd_records": self.sd.index_stats,
            "request_response_trace_count": self.request_responses.trace_count,
        }


def ensure_session_queries(state: Any) -> SessionQueries:
    """兼容旧会话或测试对象：没有查询对象时按现有消息补建一次。"""
    queries = getattr(state, "queries", None)
    if isinstance(queries, SessionQueries):
        return queries
    pipeline_result = getattr(state, "pipeline_result", None)
    type_pool = getattr(pipeline_result, "type_pool", None)
    queries = SessionQueries(
        state.messages,
        getattr(state, "registry", None),
        type_pool,
    )
    setattr(state, "queries", queries)
    return queries


__all__ = [
    "AnomalyDetailsQuery",
    "ArxmlDefinitionQuery",
    "EcuTopologyQuery",
    "MessageQuery",
    "MessageSearchResult",
    "OfferQuery",
    "PayloadValueQuery",
    "RequestResponseQuery",
    "ServiceQuery",
    "SessionComparisonQuery",
    "SessionQueries",
    "SignalQuery",
    "SubscriptionQuery",
    "build_message_evidence",
    "ensure_session_queries",
    "header_int",
    "message_service_ids",
]
