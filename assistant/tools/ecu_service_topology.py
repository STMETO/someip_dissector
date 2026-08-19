"""查询 ECU 服务角色和通信拓扑的 Tool。"""
from __future__ import annotations

from ipaddress import ip_address
from typing import Any

from .support import clamp_limit, parse_int, parse_text, require_queries

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_ecu_service_topology",
        "description": (
            "汇总 ECU/IP 的服务 Offer、请求、响应、Notification、EventGroup 订阅和通信对端。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ecu_ip": {"type": "string", "description": "可选 ECU IPv4 地址，精确匹配。"},
                "service_id": {"type": "string", "description": "可选 Service ID。"},
                "limit": {"type": "integer", "description": "最多返回 ECU 数量，默认 50，最大 200。"},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


def get_ecu_service_topology(
    session_id: str,
    ecu_ip: Any = None,
    service_id: Any = None,
    limit: Any = None,
) -> dict[str, Any]:
    """读取统一拓扑快照，Tool 本身不重新扫描报文。"""
    _, queries = require_queries(session_id)
    ip = parse_text(ecu_ip, "ecu_ip", max_length=64)
    if ip is not None:
        try:
            ip_address(ip)
        except ValueError as exc:
            raise ValueError("ecu_ip 必须是合法 IP 地址") from exc
    return queries.topology.query(
        ecu_ip=ip,
        service_id=parse_int(service_id, "Service ID"),
        limit=clamp_limit(limit, default=50, maximum=200),
    )


__all__ = ["TOOL_DEFINITION", "get_ecu_service_topology"]
