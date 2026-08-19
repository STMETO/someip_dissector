"""ECU、服务与通信方向的拓扑查询。"""
from __future__ import annotations

from ipaddress import ip_address
from typing import Any

from someip.pcap_parsers.common import (
    SOMEIP_SD_SERVICE_ID,
    get_msg_direction,
)

from .evidence import build_message_evidence, format_hex, header_int
from .message_query import MessageQuery
from .sd_query import SdRecordQuery
from .subscription_query import SubscriptionQuery

_EVIDENCE_LIMIT = 4


class EcuTopologyQuery:
    """在会话索引建立时汇总 ECU 的提供、消费、订阅和通信关系。"""

    def __init__(
        self,
        messages: MessageQuery,
        sd_records: SdRecordQuery,
        subscriptions: SubscriptionQuery,
        registry: Any = None,
    ):
        self._registry = registry
        self._rows = self._build(messages, sd_records, subscriptions.report())

    def query(
        self,
        *,
        ecu_ip: str | None = None,
        service_id: int | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """按 ECU 或 Service 过滤拓扑节点。"""
        rows = []
        for row in self._rows:
            if ecu_ip and row["ecu_ip"] != ecu_ip:
                continue
            if service_id is not None and service_id not in row["service_ids_dec"]:
                continue
            rows.append({key: value for key, value in row.items() if key != "service_ids_dec"})
        return {
            "filters": {
                "ecu_ip": ecu_ip,
                "service_id": format_hex(service_id) if service_id is not None else None,
            },
            "ecu_count": len(rows),
            "ecus": rows[:limit],
            "truncated": len(rows) > limit,
            "fact_scope": (
                "offered_services/subscribed_eventgroups 来自 SOME/IP-SD；"
                "requested/responded/notified 服务来自普通 SOME/IP 报文方向"
            ),
        }

    def _build(
        self,
        messages: MessageQuery,
        sd_records: SdRecordQuery,
        report: dict[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        nodes: dict[str, dict[str, Any]] = {}

        def node(ip: Any) -> dict[str, Any] | None:
            normalized = str(ip or "").strip()
            if not normalized or not _is_ecu_ip(normalized):
                return None
            return nodes.setdefault(normalized, _new_node(normalized))

        for message in messages.all:
            src_ip = message.get("src_ip")
            dst_ip = message.get("dst_ip")
            source = node(src_ip)
            destination = node(dst_ip)
            service_id = header_int(message, "service_id")
            if source is not None and destination is not None and src_ip != dst_ip:
                _add_peer(source, str(dst_ip), service_id, outgoing=True)
                _add_peer(destination, str(src_ip), service_id, outgoing=False)
            if service_id == SOMEIP_SD_SERVICE_ID or source is None:
                continue

            direction = get_msg_direction(header_int(message, "message_type"))
            evidence = build_message_evidence(message)
            if direction == "request":
                _add_service(source, "requested_services", service_id, evidence)
            elif direction in {"response", "error"}:
                _add_service(source, "responded_services", service_id, evidence)
            elif direction == "notification":
                _add_service(source, "notified_services", service_id, evidence)

        # Offer 使用未采样的 SD 记录，message_count 才是真实抓包计数。
        for offer in sd_records.records("offers"):
            server = node(offer.get("ecu"))
            if server is not None:
                _add_service(
                    server,
                    "offered_services",
                    int(offer.get("service_id", 0)),
                    offer.get("evidence"),
                )

        for service in report.get("services", []):
            service_id = int(service.get("service_id", 0))
            for eventgroup in service.get("eventgroups", []):
                eventgroup_id = int(eventgroup.get("eventgroup_id", 0))
                for client_ip in eventgroup.get("client_ecus", []):
                    client = node(client_ip)
                    if client is None:
                        continue
                    key = (service_id, eventgroup_id)
                    subscription = client["subscriptions"].setdefault(key, {
                        "service_id": format_hex(service_id),
                        "service_name": _service_name(self._registry, service_id),
                        "eventgroup_id": format_hex(eventgroup_id),
                        "eventgroup_name": eventgroup.get("eventgroup_name") or None,
                        "acknowledged": bool(eventgroup.get("acked")),
                        "nacked": bool(eventgroup.get("nacked")),
                        "evidence": [],
                    })
                    for evidence in eventgroup.get("subscribe_evidence", [])[:_EVIDENCE_LIMIT]:
                        _append_evidence(subscription["evidence"], evidence)

        result = []
        for ip, raw in sorted(nodes.items()):
            services = set()
            row: dict[str, Any] = {"ecu_ip": ip}
            for category in (
                "offered_services",
                "requested_services",
                "responded_services",
                "notified_services",
            ):
                values = []
                for service_id, relation in sorted(raw[category].items()):
                    services.add(service_id)
                    values.append({
                        "service_id": format_hex(service_id),
                        "service_name": _service_name(self._registry, service_id),
                        "message_count": relation["message_count"],
                        "evidence": relation["evidence"],
                    })
                row[category] = values
            subscriptions = list(raw["subscriptions"].values())
            for subscription in subscriptions:
                services.add(int(subscription["service_id"], 0))
            row["subscribed_eventgroups"] = subscriptions
            row["peers"] = [
                {
                    "peer_ip": peer_ip,
                    "outgoing_message_count": peer["outgoing"],
                    "incoming_message_count": peer["incoming"],
                    "service_ids": [format_hex(value) for value in sorted(peer["services"])],
                }
                for peer_ip, peer in sorted(raw["peers"].items())
            ]
            row["service_ids_dec"] = services
            result.append(row)
        return tuple(result)


def _new_node(ip: str) -> dict[str, Any]:
    return {
        "ecu_ip": ip,
        "offered_services": {},
        "requested_services": {},
        "responded_services": {},
        "notified_services": {},
        "subscriptions": {},
        "peers": {},
    }


def _add_service(
    node: dict[str, Any],
    category: str,
    service_id: int,
    evidence: dict[str, Any] | None,
) -> None:
    relation = node[category].setdefault(service_id, {"message_count": 0, "evidence": []})
    relation["message_count"] += 1
    if evidence:
        _append_evidence(relation["evidence"], evidence)


def _append_evidence(target: list[dict[str, Any]], evidence: dict[str, Any]) -> None:
    if len(target) >= _EVIDENCE_LIMIT:
        return
    identity = (evidence.get("message_index"), evidence.get("entry_index"))
    if any((item.get("message_index"), item.get("entry_index")) == identity for item in target):
        return
    target.append(evidence)


def _add_peer(node: dict[str, Any], peer_ip: str, service_id: int, *, outgoing: bool) -> None:
    peer = node["peers"].setdefault(
        peer_ip, {"outgoing": 0, "incoming": 0, "services": set()}
    )
    peer["outgoing" if outgoing else "incoming"] += 1
    if service_id != SOMEIP_SD_SERVICE_ID:
        peer["services"].add(service_id)


def _service_name(registry: Any, service_id: int) -> str | None:
    try:
        return registry.lookup_service_name(service_id) if registry else None
    except Exception:
        return None


def _is_ecu_ip(value: str) -> bool:
    """组播和未指定地址是通信端点，不作为 ECU 节点展示。"""
    try:
        address = ip_address(value)
    except ValueError:
        return False
    return not address.is_multicast and not address.is_unspecified


__all__ = ["EcuTopologyQuery"]
