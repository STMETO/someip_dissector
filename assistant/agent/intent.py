"""结构化意图、实体 Schema 与确定性 Tool 子集策略。"""
from __future__ import annotations

from enum import Enum
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self


class SomeIpIntent(str, Enum):
    """当前 Agent 支持的有限意图集合。"""

    MODEL_IDENTITY = "model_identity"
    CAPABILITIES = "capabilities"
    SERVICE_LOOKUP = "service_lookup"
    OFFER_ANALYSIS = "offer_analysis"
    SUBSCRIPTION_DIAGNOSTIC = "subscription_diagnostic"
    MESSAGE_SEARCH = "message_search"
    NOTIFICATION_ANALYSIS = "notification_analysis"
    PAYLOAD_ANALYSIS = "payload_analysis"
    REQUEST_RESPONSE = "request_response"
    ECU_TOPOLOGY = "ecu_topology"
    ARXML_DEFINITION = "arxml_definition"
    SESSION_COMPARISON = "session_comparison"
    GENERAL_DIAGNOSTIC = "general_diagnostic"
    GENERAL_CONVERSATION = "general_conversation"


class IntentEntities(BaseModel):
    """从问题中识别出的 SOME/IP 查询实体。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    service_id: str | None = Field(default=None, max_length=32)
    method_or_event_id: str | None = Field(default=None, max_length=32)
    eventgroup_id: str | None = Field(default=None, max_length=32)
    instance_id: str | None = Field(default=None, max_length=32)
    message_index: int | None = Field(default=None, ge=0, le=100_000_000)
    ecu_ip: str | None = Field(default=None, max_length=64)
    client_ip: str | None = Field(default=None, max_length=64)
    field_path: str | None = Field(default=None, max_length=1000)
    start_time: float | None = None
    end_time: float | None = None
    comparison_session_ids: list[str] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def validate_time_range(self) -> Self:
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.start_time > self.end_time
        ):
            raise ValueError("start_time 不能大于 end_time")
        return self


class IntentClassification(BaseModel):
    """分类模型必须返回的结构化结果，不接受自由扩展字段。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    intent: SomeIpIntent
    requires_tools: bool
    confidence: float = Field(ge=0.0, le=1.0)
    entities: IntentEntities = Field(default_factory=IntentEntities)
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=500)
    scope: Literal["current_session", "cross_session"] = "current_session"
    complexity: Literal["simple", "complex"] = "simple"
    answer_kind: Literal["lookup", "diagnosis", "report", "explanation"] = "lookup"

    @model_validator(mode="after")
    def validate_clarification(self) -> Self:
        if self.needs_clarification and not self.clarification_question:
            raise ValueError("需要澄清时必须提供 clarification_question")
        return self


_TOOL_POLICY: dict[SomeIpIntent, tuple[str, ...]] = {
    SomeIpIntent.SERVICE_LOOKUP: (
        "find_service",
        "get_subscription_status",
        "get_arxml_definition",
    ),
    SomeIpIntent.OFFER_ANALYSIS: (
        "find_service",
        "get_offer_timeline",
        "get_subscription_status",
        "get_anomaly_details",
    ),
    SomeIpIntent.SUBSCRIPTION_DIAGNOSTIC: (
        "get_subscription_status",
        "get_subscription_timeline",
        "get_offer_timeline",
        "get_anomaly_details",
        "find_service",
    ),
    SomeIpIntent.MESSAGE_SEARCH: (
        "search_messages",
        "get_message_detail",
        "find_service",
    ),
    SomeIpIntent.NOTIFICATION_ANALYSIS: (
        "get_notification_statistics",
        "search_messages",
        "get_payload_field",
        "get_subscription_timeline",
        "find_service",
    ),
    SomeIpIntent.PAYLOAD_ANALYSIS: (
        "search_messages",
        "get_message_detail",
        "get_payload_field",
        "search_payload_values",
        "get_arxml_definition",
        "find_service",
    ),
    SomeIpIntent.REQUEST_RESPONSE: (
        "get_request_response_trace",
        "search_messages",
        "get_message_detail",
        "find_service",
    ),
    SomeIpIntent.ECU_TOPOLOGY: (
        "get_ecu_service_topology",
        "find_service",
        "get_subscription_status",
    ),
    SomeIpIntent.ARXML_DEFINITION: (
        "get_arxml_definition",
        "find_service",
    ),
    SomeIpIntent.SESSION_COMPARISON: (
        "compare_sessions",
        "get_subscription_status",
        "get_anomaly_details",
    ),
}


def select_tools(intent: SomeIpIntent) -> list[str]:
    """按服务端策略选择 Tool，分类模型不能直接提交 Tool 名称。"""
    if intent == SomeIpIntent.GENERAL_DIAGNOSTIC:
        # 综合报告可能跨越所有领域，只有该意图允许暴露完整只读 Tool 集。
        from ..integrations.langchain.tools import LANGCHAIN_TOOLS

        return [tool.name for tool in LANGCHAIN_TOOLS]
    return list(_TOOL_POLICY.get(intent, ()))


def deterministic_fallback(question: str) -> IntentClassification:
    """结构化分类失败时提供保守回退，保证错误不会扩大 Tool 权限。"""
    normalized = question.casefold()
    intent = _fallback_intent(normalized)
    requires_tools = intent not in {
        SomeIpIntent.MODEL_IDENTITY,
        SomeIpIntent.CAPABILITIES,
        SomeIpIntent.GENERAL_CONVERSATION,
    }
    ids = re.findall(r"0x[0-9a-f]{1,8}", normalized)
    ips = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", normalized)
    entities = IntentEntities(
        service_id=ids[0] if ids else None,
        method_or_event_id=ids[1] if len(ids) > 1 else None,
        ecu_ip=ips[0] if ips else None,
    )
    return IntentClassification(
        intent=intent,
        requires_tools=requires_tools,
        confidence=0.35,
        entities=entities,
        scope=(
            "cross_session"
            if intent == SomeIpIntent.SESSION_COMPARISON
            else "current_session"
        ),
    )


def _fallback_intent(question: str) -> SomeIpIntent:
    if any(value in question for value in ("什么模型", "哪种模型", "what model")):
        return SomeIpIntent.MODEL_IDENTITY
    if any(value in question for value in ("能做什么", "哪些能力", "capabilit")):
        return SomeIpIntent.CAPABILITIES
    if any(value in question for value in ("对比", "比较会话", "compare session")):
        return SomeIpIntent.SESSION_COMPARISON
    if "arxml" in question or "数据类型" in question:
        return SomeIpIntent.ARXML_DEFINITION
    if any(value in question for value in ("request", "response", "响应时间")):
        return SomeIpIntent.REQUEST_RESPONSE
    if any(value in question for value in ("payload", "字段值", "信号值")):
        return SomeIpIntent.PAYLOAD_ANALYSIS
    if any(value in question for value in ("notification", "通知", "频率", "跳变")):
        return SomeIpIntent.NOTIFICATION_ANALYSIS
    if any(value in question for value in ("拓扑", "ecu", "通信对端")):
        return SomeIpIntent.ECU_TOPOLOGY
    if any(value in question for value in ("subscribe", "订阅", "ack", "nack", "eventgroup")):
        return SomeIpIntent.SUBSCRIPTION_DIAGNOSTIC
    if "offer" in question or "发布服务" in question:
        return SomeIpIntent.OFFER_ANALYSIS
    if any(value in question for value in ("报文", "消息", "frame", "message")):
        return SomeIpIntent.MESSAGE_SEARCH
    if any(value in question for value in ("抓包", "pcap", "诊断", "服务")):
        return SomeIpIntent.GENERAL_DIAGNOSTIC
    return SomeIpIntent.GENERAL_CONVERSATION


__all__ = [
    "IntentClassification",
    "IntentEntities",
    "SomeIpIntent",
    "deterministic_fallback",
    "select_tools",
]
