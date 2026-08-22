"""十四个 SOME/IP LangChain Tool 的强类型参数模型。

这些 Schema 是模型可见参数的唯一来源。解析会话、查询对象、API Key、取消信号和
执行预算属于服务端运行时依赖，禁止放入这些模型，避免模型伪造权限或内部状态。
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self


ServiceId = Annotated[
    str,
    Field(min_length=1, max_length=32, description="Service ID，例如 0x0A01。"),
]
MemberId = Annotated[
    str,
    Field(min_length=1, max_length=32, description="SOME/IP 成员 ID，支持十六进制或十进制。"),
]
EpochSeconds = Annotated[float, Field(description="Unix epoch 秒，可包含小数。")]
Offset = Annotated[int, Field(ge=0, le=10_000_000, description="分页偏移。")]


class StrictToolArgs(BaseModel):
    """所有 Tool 参数的共同安全基类。"""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        str_strip_whitespace=True,
        validate_default=True,
    )


class TimeRangeArgs(StrictToolArgs):
    """带时间范围的 Tool 公共参数与顺序校验。"""

    start_time: EpochSeconds | None = Field(default=None, description="可选起始 epoch 秒。")
    end_time: EpochSeconds | None = Field(default=None, description="可选结束 epoch 秒。")

    @model_validator(mode="after")
    def validate_time_range(self) -> Self:
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.start_time > self.end_time
        ):
            raise ValueError("start_time 不能大于 end_time")
        return self


class SubscriptionStatusArgs(StrictToolArgs):
    service_id: ServiceId | None = Field(
        default=None,
        description="可选 Service ID；为空时返回抓包中的全部服务诊断总览。",
    )


class FindServiceArgs(StrictToolArgs):
    query: Annotated[str, Field(max_length=256)] | None = Field(
        default=None,
        description="十六进制 ID、十进制 ID 或 ARXML 服务名称；为空时列出服务。",
    )
    limit: Annotated[int, Field(ge=1, le=50)] = Field(
        default=20,
        description="最大返回数量，默认 20，最大 50。",
    )


class OfferTimelineArgs(TimeRangeArgs):
    service_id: ServiceId
    instance_id: MemberId | None = Field(default=None, description="可选 Instance ID。")
    offset: Offset = 0
    limit: Annotated[int, Field(ge=1, le=200)] = Field(
        default=50,
        description="返回时间线条数，默认 50，最大 200。",
    )


class SubscriptionTimelineArgs(TimeRangeArgs):
    service_id: ServiceId
    eventgroup_id: MemberId | None = Field(default=None, description="可选 EventGroup ID。")
    instance_id: MemberId | None = Field(default=None, description="可选 Instance ID。")
    client_ip: Annotated[str, Field(min_length=1, max_length=64)] | None = Field(
        default=None,
        description="可选订阅客户端 IP，精确匹配。",
    )
    offset: Offset = 0
    limit: Annotated[int, Field(ge=1, le=200)] = Field(
        default=80,
        description="返回时间线条数，默认 80，最大 200。",
    )


class SearchMessagesArgs(TimeRangeArgs):
    service_id: ServiceId | None = None
    method_id: MemberId | None = Field(default=None, description="可选 Method/Event ID。")
    message_type: Annotated[str, Field(min_length=1, max_length=64)] | None = Field(
        default=None,
        description="可选消息类型，例如 0x02、Notification 或 Offer。",
    )
    src_ip: Annotated[str, Field(min_length=1, max_length=64)] | None = Field(
        default=None,
        description="可选源 IP，精确匹配。",
    )
    dst_ip: Annotated[str, Field(min_length=1, max_length=64)] | None = Field(
        default=None,
        description="可选目标 IP，精确匹配。",
    )
    sd_entry_type: Annotated[str, Field(min_length=1, max_length=64)] | None = Field(
        default=None,
        description="可选 SD Entry 类型，例如 OfferService。",
    )
    parse_status: Annotated[str, Field(min_length=1, max_length=64)] | None = Field(
        default=None,
        description="可选解析状态，例如 ok 或 unresolved。",
    )
    offset: Offset = 0
    limit: Annotated[int, Field(ge=1, le=200)] = Field(
        default=50,
        description="返回报文数量，默认 50，最大 200。",
    )


class MessageDetailArgs(StrictToolArgs):
    message_index: Annotated[int, Field(ge=0, le=100_000_000)] = Field(
        description="消息列表中的 Index。",
    )
    include_payload_hex: bool = Field(
        default=False,
        description="是否包含原始 Payload hex；大字段可能被 Tool 自身截断。",
    )
    include_parsed_tree: bool = Field(
        default=True,
        description="是否包含反序列化解析树，默认包含。",
    )


class NotificationStatisticsArgs(TimeRangeArgs):
    service_id: ServiceId | None = None
    method_id: MemberId | None = Field(default=None, description="可选 Method/Event ID。")
    field_path: Annotated[str, Field(min_length=1, max_length=1000)] | None = Field(
        default=None,
        description="可选 Payload 字段路径，例如 status.speed。",
    )

    @model_validator(mode="after")
    def validate_filter_dependencies(self) -> Self:
        if self.method_id is not None and self.service_id is None:
            raise ValueError("按 Method/Event ID 查询时必须同时提供 Service ID")
        if self.field_path is not None and self.method_id is None:
            raise ValueError("统计 Payload 字段时必须提供 Service ID 和 Method/Event ID")
        return self


class PayloadFieldArgs(StrictToolArgs):
    message_index: Annotated[int, Field(ge=0, le=100_000_000)] = Field(
        description="消息列表中的 Index。",
    )
    field_path: Annotated[str, Field(min_length=1, max_length=1000)] = Field(
        description="点分隔 Payload 字段路径，例如 vehicle.status.speed。",
    )


class RequestResponseTraceArgs(TimeRangeArgs):
    service_id: ServiceId | None = None
    method_id: MemberId | None = Field(default=None, description="可选 Method ID。")
    client_id: MemberId | None = Field(default=None, description="可选 SOME/IP Client ID。")
    # 这里是报文头中的 SOME/IP Session ID，不是服务端解析会话 ID。
    session_id: MemberId | None = Field(default=None, description="可选 SOME/IP Session ID。")
    status: Literal[
        "matched",
        "error_response",
        "missing_response",
        "unmatched_response",
        "no_return",
    ] | None = Field(default=None, description="可选 Request/Response 关联状态。")
    offset: Offset = 0
    limit: Annotated[int, Field(ge=1, le=200)] = Field(
        default=80,
        description="返回关联记录数量，默认 80，最大 200。",
    )


class EcuServiceTopologyArgs(StrictToolArgs):
    ecu_ip: Annotated[str, Field(min_length=1, max_length=64)] | None = Field(
        default=None,
        description="可选 ECU IP，精确匹配。",
    )
    service_id: ServiceId | None = None
    limit: Annotated[int, Field(ge=1, le=200)] = Field(
        default=50,
        description="最多返回 ECU 数量，默认 50，最大 200。",
    )


class ArxmlDefinitionArgs(StrictToolArgs):
    service_id: ServiceId
    member_kind: Literal["all", "method", "event", "eventgroup"] = Field(
        default="all",
        description="成员类型，默认 all。",
    )
    member_id: MemberId | None = Field(
        default=None,
        description="可选 Method、Event 或 EventGroup ID。",
    )
    field_path: Annotated[str, Field(min_length=1, max_length=512)] | None = Field(
        default=None,
        description="可选字段路径；提供后只返回匹配字段定义。",
    )


class PayloadValueSearchArgs(TimeRangeArgs):
    field_path: Annotated[str, Field(min_length=1, max_length=512)] = Field(
        description="必填字段路径，例如 status.speed。",
    )
    service_id: ServiceId | None = None
    method_id: MemberId | None = Field(default=None, description="可选 Method/Event ID。")
    exact_value: Annotated[str, Field(max_length=1024)] | None = Field(
        default=None,
        description="可选精确值；数值和布尔也使用字符串，例如 42 或 true。",
    )
    text_contains: Annotated[str, Field(max_length=512)] | None = Field(
        default=None,
        description="可选文本包含条件。",
    )
    minimum: float | None = Field(default=None, description="可选数值下限，包含边界。")
    maximum: float | None = Field(default=None, description="可选数值上限，包含边界。")
    offset: Offset = 0
    limit: Annotated[int, Field(ge=1, le=200)] = Field(
        default=80,
        description="返回字段命中数量，默认 80，最大 200。",
    )

    @model_validator(mode="after")
    def validate_numeric_range(self) -> Self:
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("minimum 不能大于 maximum")
        return self


class AnomalyDetailsArgs(StrictToolArgs):
    anomaly_type: Literal[
        "all",
        "offer_conflict",
        "offered_without_subscription",
        "subscribed_without_offer",
        "subscribed_without_ack",
        "nacked",
        "subscribed_without_notification",
    ] = Field(default="all", description="需要展开的诊断异常类型。")
    service_id: ServiceId | None = None
    offset: Offset = 0
    limit: Annotated[int, Field(ge=1, le=200)] = Field(
        default=80,
        description="返回异常数量，默认 80，最大 200。",
    )


class CompareSessionsArgs(StrictToolArgs):
    session_ids: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=128)]],
        Field(min_length=1, max_length=3),
    ] = Field(
        description="一到三个已由用户授权的目标解析会话 ID，不包含当前会话。",
    )


TOOL_ARGS_SCHEMAS: dict[str, type[StrictToolArgs]] = {
    "get_subscription_status": SubscriptionStatusArgs,
    "find_service": FindServiceArgs,
    "get_offer_timeline": OfferTimelineArgs,
    "get_subscription_timeline": SubscriptionTimelineArgs,
    "search_messages": SearchMessagesArgs,
    "get_message_detail": MessageDetailArgs,
    "get_notification_statistics": NotificationStatisticsArgs,
    "get_payload_field": PayloadFieldArgs,
    "get_request_response_trace": RequestResponseTraceArgs,
    "get_ecu_service_topology": EcuServiceTopologyArgs,
    "get_arxml_definition": ArxmlDefinitionArgs,
    "search_payload_values": PayloadValueSearchArgs,
    "get_anomaly_details": AnomalyDetailsArgs,
    "compare_sessions": CompareSessionsArgs,
}


__all__ = [
    "TOOL_ARGS_SCHEMAS",
    "AnomalyDetailsArgs",
    "ArxmlDefinitionArgs",
    "CompareSessionsArgs",
    "EcuServiceTopologyArgs",
    "FindServiceArgs",
    "MessageDetailArgs",
    "NotificationStatisticsArgs",
    "OfferTimelineArgs",
    "PayloadFieldArgs",
    "PayloadValueSearchArgs",
    "RequestResponseTraceArgs",
    "SearchMessagesArgs",
    "StrictToolArgs",
    "SubscriptionStatusArgs",
    "SubscriptionTimelineArgs",
]
