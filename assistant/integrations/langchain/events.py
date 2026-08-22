"""LangGraph 标准流事件到 Web NDJSON 契约的适配器。"""
from __future__ import annotations

from threading import Event
from typing import Any, Callable

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from ...execution.run_record import AssistantRunRecord


ProgressCallback = Callable[[dict[str, Any]], None]


_TOOL_PROGRESS_LABELS = {
    "get_subscription_status": "正在查询订阅诊断总览",
    "find_service": "正在查找服务",
    "get_offer_timeline": "正在查询 Offer 时间线",
    "get_subscription_timeline": "正在查询订阅时间线",
    "search_messages": "正在检索报文",
    "get_message_detail": "正在读取报文详情",
    "get_notification_statistics": "正在统计 Notification",
    "get_payload_field": "正在读取 Payload 字段",
    "get_request_response_trace": "正在关联 Request/Response",
    "get_ecu_service_topology": "正在构建 ECU 服务拓扑",
    "get_arxml_definition": "正在查询 ARXML 定义",
    "search_payload_values": "正在检索 Payload 字段值",
    "get_anomaly_details": "正在展开诊断异常",
    "compare_sessions": "正在比较解析记录",
}


class GraphStreamCancelled(RuntimeError):
    """消费 Graph 流时检测到用户取消。"""


class LangGraphEventAdapter:
    """消费 ``messages/updates/values``，保留现有前端事件协议。

    适配器不读取模型厂商私有字段。Tool 参数来自 AIMessage 的标准 Tool Call，
    执行结果和导航链接来自 ToolMessage artifact，最终答案来自 ``finish`` 节点。
    """

    def __init__(
        self,
        run_record: AssistantRunRecord,
        progress: ProgressCallback | None = None,
        cancel_event: Event | None = None,
    ) -> None:
        self.run_record = run_record
        self.progress = progress
        self.cancel_event = cancel_event
        self.final_state: dict[str, Any] = {}
        self.tools: list[dict[str, Any]] = []
        self._preview = ""
        self._started_tool_calls: set[str] = set()
        self._finished_tool_calls: set[str] = set()
        self._usage_messages: set[str] = set()

    def consume(self, event: Any) -> None:
        """消费 LangGraph v2 流分片，并立即发送可见进度。"""
        self._check_cancel()
        if not isinstance(event, dict):
            return
        event_type = str(event.get("type") or "")
        namespace = tuple(str(item) for item in event.get("ns", ()))
        data = event.get("data")
        if event_type == "messages":
            self._consume_message(data, namespace)
        elif event_type == "updates":
            self._consume_updates(data, namespace)
        elif event_type == "values" and not namespace and isinstance(data, dict):
            self.final_state = data

    def publish_final_answer(self, answer: str) -> None:
        """保证浏览器最终预览与 Guard/Revision 后的答案完全一致。"""
        normalized = str(answer or "").strip()
        if normalized == self._preview:
            return
        self._notify({"type": "text_reset"})
        if normalized:
            self._notify({"type": "text_delta", "delta": normalized})
        self._preview = normalized

    def _consume_message(self, data: Any, namespace: tuple[str, ...]) -> None:
        if not isinstance(data, tuple) or len(data) != 2:
            return
        message, metadata = data
        if not isinstance(message, BaseMessage):
            return
        metadata = metadata if isinstance(metadata, dict) else {}
        self._collect_usage(message)
        if isinstance(message, ToolMessage):
            self._tool_end(message)
            return
        if not isinstance(message, AIMessage):
            return
        if not self._is_visible_answer_message(message, metadata, namespace):
            return
        text = _message_text(message)
        if text:
            self._preview += text
            self._notify({"type": "text_delta", "delta": text})

    def _consume_updates(self, data: Any, namespace: tuple[str, ...]) -> None:
        if not isinstance(data, dict):
            return
        for node, update in data.items():
            qualified_node = "/".join((*namespace, str(node)))
            status = update.get("status") if isinstance(update, dict) else None
            self.run_record.add_graph_event(qualified_node, str(status or "updated"))
            # 内层 ReAct 的 model 更新包含本轮完整 Tool Call，适合生成准确参数预览。
            if str(node) == "model" and namespace and isinstance(update, dict):
                for message in _messages_from_update(update):
                    self._tool_starts(message)
            if not namespace and str(node) == "finish" and isinstance(update, dict):
                self.publish_final_answer(str(update.get("final_answer") or ""))

    def _tool_starts(self, message: BaseMessage) -> None:
        if not isinstance(message, AIMessage):
            return
        calls = list(getattr(message, "tool_calls", []) or [])
        if calls:
            # 模型在 Tool Call 之前输出的文字不是最终答案。
            self._preview = ""
            self._notify({"type": "text_reset"})
        for call in calls:
            call_id = str(call.get("id") or f"tool-{len(self._started_tool_calls) + 1}")
            if call_id in self._started_tool_calls:
                continue
            self._started_tool_calls.add(call_id)
            name = str(call.get("name") or "unknown")
            arguments = call.get("args") if isinstance(call.get("args"), dict) else {}
            self._notify({
                "type": "tool_start",
                "name": name,
                "arguments": arguments,
                "message": _TOOL_PROGRESS_LABELS.get(name, f"正在调用 {name}"),
            })

    def _tool_end(self, message: ToolMessage) -> None:
        call_id = str(message.tool_call_id or message.id or "")
        if call_id and call_id in self._finished_tool_calls:
            return
        if call_id:
            self._finished_tool_calls.add(call_id)
        artifact = message.artifact if isinstance(message.artifact, dict) else {}
        execution = artifact.get("execution")
        execution = execution if isinstance(execution, dict) else {}
        name = str(message.name or artifact.get("tool") or "unknown")
        status = str(execution.get("status") or message.status or "failed")
        arguments = artifact.get("arguments")
        arguments = arguments if isinstance(arguments, dict) else {}
        links = artifact.get("navigation_links")
        links = [item for item in links or [] if isinstance(item, dict)]
        record = {
            "name": name,
            "arguments": arguments,
            "links": links,
            "status": status,
            "ok": status == "success",
            "error_code": execution.get("error_code"),
            "duration_ms": int(execution.get("duration_ms") or 0),
            "result_bytes": int(execution.get("result_bytes") or 0),
        }
        self.tools.append(record)
        completion = (
            "完成"
            if status == "success"
            else "部分完成"
            if status == "partial"
            else "失败"
        )
        self._notify({
            "type": "tool_end",
            **record,
            "message": (
                f"{_TOOL_PROGRESS_LABELS.get(name, name).removeprefix('正在')}"
                f"{completion}"
            ),
        })

    def _collect_usage(self, message: BaseMessage) -> None:
        usage = getattr(message, "usage_metadata", None)
        if not isinstance(usage, dict) or not usage:
            return
        identity = str(message.id or id(message))
        if identity in self._usage_messages:
            return
        self._usage_messages.add(identity)
        self.run_record.add_usage(usage)

    @staticmethod
    def _is_visible_answer_message(
        message: AIMessage,
        metadata: dict[str, Any],
        namespace: tuple[str, ...],
    ) -> bool:
        node = str(metadata.get("langgraph_node") or "")
        if node == "direct_answer" and not namespace:
            return not bool(message.tool_calls)
        # 内层 create_agent 的模型消息才是诊断草稿；分类和 Reflection 的
        # Structured Output 也表现为 Tool Call，必须排除。
        return bool(namespace) and node == "model" and not bool(message.tool_calls)

    def _check_cancel(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise GraphStreamCancelled("请求已取消")

    def _notify(self, event: dict[str, Any]) -> None:
        if self.progress is None:
            return
        try:
            self.progress(event)
        except Exception:
            # 浏览器断开或测试回调失败不能污染 Graph State。
            return


def _messages_from_update(update: dict[str, Any]) -> list[BaseMessage]:
    value = update.get("messages")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, BaseMessage)]


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get("text"):
            parts.append(str(item["text"]))
    return "".join(parts)


__all__ = ["GraphStreamCancelled", "LangGraphEventAdapter", "ProgressCallback"]
