"""SOME/IP Request/Response 关联查询。"""
from __future__ import annotations

from collections import defaultdict, deque
from statistics import mean, median
from typing import Any

from someip.pcap_parsers.common import SOMEIP_SD_SERVICE_ID, message_type_label

from .evidence import build_message_evidence, format_hex, header_int, in_time_range
from .message_query import MessageQuery

_REQUEST_TYPES = {0x00, 0x20}
_NO_RETURN_TYPES = {0x01, 0x21}
_RESPONSE_TYPES = {0x80, 0xA0}
_ERROR_TYPES = {0x81}
_ALLOWED_STATUSES = {
    "matched",
    "error_response",
    "missing_response",
    "unmatched_response",
    "no_return",
}


class RequestResponseQuery:
    """按 SOME/IP 关联键构建一次 RPC 调用轨迹。

    关联键使用 ``Service ID + Method ID + Client ID + Session ID``。同一个键
    出现重传时按抓包顺序先进先出匹配，并优先选择网络端点反向对应的请求。
    """

    def __init__(self, messages: MessageQuery, registry: Any = None):
        self._registry = registry
        self._traces = self._build_traces(messages.all)

    @property
    def trace_count(self) -> int:
        return len(self._traces)

    def search(
        self,
        *,
        service_id: int | None = None,
        method_id: int | None = None,
        client_id: int | None = None,
        session_id: int | None = None,
        status: str = "",
        start_time: float | None = None,
        end_time: float | None = None,
        offset: int = 0,
        limit: int = 80,
    ) -> dict[str, Any]:
        """筛选 RPC 轨迹并返回延迟统计和有限证据。"""
        normalized_status = status.strip().casefold()
        if normalized_status and normalized_status not in _ALLOWED_STATUSES:
            raise ValueError(
                "status 必须是 matched、error_response、missing_response、"
                "unmatched_response 或 no_return"
            )

        matched: list[dict[str, Any]] = []
        for trace in self._traces:
            if service_id is not None and trace["service_id_dec"] != service_id:
                continue
            if method_id is not None and trace["method_id_dec"] != method_id:
                continue
            if client_id is not None and trace["client_id_dec"] != client_id:
                continue
            if session_id is not None and trace["session_id_dec"] != session_id:
                continue
            if normalized_status and trace["status"] != normalized_status:
                continue
            evidence = trace.get("request_evidence") or trace.get("response_evidence") or {}
            if not in_time_range(evidence, start_time, end_time):
                continue
            matched.append(trace)

        durations = [
            float(trace["response_time_ms"])
            for trace in matched
            if trace.get("response_time_ms") is not None
        ]
        status_counts: dict[str, int] = defaultdict(int)
        for trace in matched:
            status_counts[trace["status"]] += 1
        page = matched[offset:offset + limit]
        return {
            "filters": {
                "service_id": format_hex(service_id) if service_id is not None else None,
                "method_id": format_hex(method_id) if method_id is not None else None,
                "client_id": format_hex(client_id) if client_id is not None else None,
                "session_id": format_hex(session_id) if session_id is not None else None,
                "status": normalized_status or None,
                "start_time": start_time,
                "end_time": end_time,
            },
            "summary": {
                "trace_count": len(matched),
                "status_counts": dict(sorted(status_counts.items())),
                "response_time_ms": {
                    "sample_count": len(durations),
                    "average": round(mean(durations), 3) if durations else None,
                    "median": round(median(durations), 3) if durations else None,
                    "maximum": round(max(durations), 3) if durations else None,
                },
            },
            "association_rule": (
                "按 Service ID、Method ID、Client ID、Session ID 关联，"
                "重传按抓包顺序匹配并优先校验反向网络端点"
            ),
            "offset": offset,
            "next_offset": offset + len(page) if offset + len(page) < len(matched) else None,
            "traces": page,
        }

    def _build_traces(
        self,
        messages: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, Any], ...]:
        pending: dict[tuple[int, int, int, int], deque[dict[str, Any]]] = defaultdict(deque)
        traces: list[dict[str, Any]] = []

        for message in messages:
            service_id = header_int(message, "service_id")
            if service_id == SOMEIP_SD_SERVICE_ID:
                continue
            method_id = header_int(message, "method_id")
            client_id = header_int(message, "client_id")
            session_id = header_int(message, "session_id")
            message_type = header_int(message, "message_type")
            key = (service_id, method_id, client_id, session_id)

            if message_type in _REQUEST_TYPES:
                pending[key].append(message)
                continue
            if message_type in _NO_RETURN_TYPES:
                traces.append(self._make_trace(message, None, "no_return"))
                continue
            if message_type not in _RESPONSE_TYPES | _ERROR_TYPES:
                continue

            request = _take_matching_request(pending[key], message)
            status = (
                "unmatched_response" if request is None
                else "error_response" if message_type in _ERROR_TYPES
                else "matched"
            )
            traces.append(self._make_trace(request, message, status))

        for requests in pending.values():
            for request in requests:
                traces.append(self._make_trace(request, None, "missing_response"))

        traces.sort(key=lambda trace: (
            float((trace.get("request_evidence") or trace.get("response_evidence") or {}).get(
                "timestamp_epoch", 0.0
            )),
            int((trace.get("request_evidence") or trace.get("response_evidence") or {}).get(
                "message_index", -1
            )),
        ))
        return tuple(traces)

    def _make_trace(
        self,
        request: dict[str, Any] | None,
        response: dict[str, Any] | None,
        status: str,
    ) -> dict[str, Any]:
        source = request or response or {}
        service_id = header_int(source, "service_id")
        method_id = header_int(source, "method_id")
        client_id = header_int(source, "client_id")
        session_id = header_int(source, "session_id")
        response_type = header_int(response, "message_type") if response else None
        duration = None
        if request is not None and response is not None:
            duration = max(
                0.0,
                (float(response.get("timestamp_epoch") or 0.0)
                 - float(request.get("timestamp_epoch") or 0.0)) * 1000,
            )
        return {
            "status": status,
            "service_id": format_hex(service_id),
            "service_id_dec": service_id,
            "service_name": _lookup_name(self._registry, "service", service_id, method_id),
            "method_id": format_hex(method_id),
            "method_id_dec": method_id,
            "method_name": _lookup_name(self._registry, "method", service_id, method_id),
            "client_id": format_hex(client_id),
            "client_id_dec": client_id,
            "session_id": format_hex(session_id),
            "session_id_dec": session_id,
            "response_type": (
                message_type_label(response_type) if response_type is not None else None
            ),
            "return_code": (
                format_hex(header_int(response, "return_code"), 2) if response else None
            ),
            "response_time_ms": round(duration, 3) if duration is not None else None,
            "request_evidence": (
                build_message_evidence(request, kind="Request") if request else None
            ),
            "response_evidence": (
                build_message_evidence(
                    response,
                    kind="Error" if response_type in _ERROR_TYPES else "Response",
                ) if response else None
            ),
        }


def _take_matching_request(
    requests: deque[dict[str, Any]],
    response: dict[str, Any],
) -> dict[str, Any] | None:
    """优先匹配源/目标端点反向的请求，缺少端点信息时按 FIFO。"""
    if not requests:
        return None
    response_src = response.get("src_ip")
    response_dst = response.get("dst_ip")
    for index, request in enumerate(requests):
        if request.get("src_ip") == response_dst and request.get("dst_ip") == response_src:
            requests.rotate(-index)
            matched = requests.popleft()
            requests.rotate(index)
            return matched
    return requests.popleft()


def _lookup_name(registry: Any, kind: str, service_id: int, method_id: int) -> str | None:
    try:
        if not registry:
            return None
        if kind == "service":
            return registry.lookup_service_name(service_id)
        return registry.lookup_method_name(service_id, method_id)
    except Exception:
        return None


__all__ = ["RequestResponseQuery"]
