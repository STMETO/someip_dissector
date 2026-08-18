"""
SD 订阅诊断 — 纯后端逻辑。

诊断规则（pcap 视角）：
- 服务端：发出 Offer → 是否收到 Subscribe？→ 是否发出 Notification？
- 客户端：发出 Subscribe → 是否收到 Notification？
"""
from __future__ import annotations
from collections import defaultdict
from typing import Any

from pcap_parsers.common import SOMEIP_SD_SERVICE_ID, is_notification

_SD_SERVICE_ID = SOMEIP_SD_SERVICE_ID


# ═══════════════════════════════════════════════════════════════════
# SD 记录提取
# ═══════════════════════════════════════════════════════════════════

def extract_sd_records(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """从消息中提取带报文证据的 SD 生命周期记录。

    返回值保留 Offer、停止 Offer、订阅、停止订阅、Ack 和 Nack 六类
    记录。上层诊断和 AI Tool 共用这份结构，避免各自重复解释 SD Entry。
    """
    offers: list[dict[str, Any]] = []
    stop_offers: list[dict[str, Any]] = []
    subscribes: list[dict[str, Any]] = []
    stop_subscribes: list[dict[str, Any]] = []
    subscribe_acks: list[dict[str, Any]] = []
    subscribe_nacks: list[dict[str, Any]] = []

    for msg in messages:
        sd = msg.get("sd")
        if not isinstance(sd, dict):
            continue
        src_ip = msg.get("src_ip", "?")

        for entry_index, entry in enumerate(sd.get("entries", [])):
            etype = entry.get("type", "")
            srv_id = _dec(entry.get("service_id"))
            inst_id = _dec(entry.get("instance_id"))
            record = {
                "entry_type": etype,
                "entry_index": entry_index,
                "service_id": srv_id,
                "instance_id": inst_id,
                "ecu": src_ip,
                "ttl": _dec(entry.get("ttl")),
                "major_version": _dec(entry.get("major_version")),
                "minor_version": _dec(entry.get("minor_version")),
                "evidence": build_message_evidence(
                    msg,
                    kind=etype,
                    entry_index=entry_index,
                ),
            }

            if etype in {"OfferService", "StopOfferService"}:
                if etype == "StopOfferService" or record["ttl"] == 0:
                    stop_offers.append(record)
                else:
                    offers.append(record)
            elif etype == "SubscribeEventGroup":
                record["eventgroup_id"] = _dec(entry.get("eventgroup_id"))
                if record["ttl"] == 0:
                    stop_subscribes.append(record)
                else:
                    subscribes.append(record)
            elif etype in ("SubscribeEventGroupAck", "SubscribeEventgroupAck"):
                record["eventgroup_id"] = _dec(entry.get("eventgroup_id"))
                subscribe_acks.append(record)
            elif etype in ("SubscribeEventGroupNack", "SubscribeEventgroupNack"):
                record["eventgroup_id"] = _dec(entry.get("eventgroup_id"))
                subscribe_nacks.append(record)

    return {
        "offers": offers,
        "stop_offers": stop_offers,
        "subscribes": subscribes,
        "stop_subscribes": stop_subscribes,
        "subscribe_acks": subscribe_acks,
        "subscribe_nacks": subscribe_nacks,
    }


def build_message_evidence(
    message: dict[str, Any],
    *,
    kind: str = "",
    entry_index: int | None = None,
) -> dict[str, Any]:
    """生成可供页面跳转和人工复核的最小报文证据。"""
    evidence = {
        "message_index": message.get("index"),
        "frame_index": message.get("frame_index"),
        "timestamp_epoch": message.get("timestamp_epoch", 0.0),
        "timestamp_iso": message.get("timestamp_iso", ""),
        "transport": message.get("transport", ""),
        "src_ip": message.get("src_ip"),
        "src_port": message.get("src_port"),
        "dst_ip": message.get("dst_ip"),
        "dst_port": message.get("dst_port"),
        "kind": kind or message.get("message_kind", ""),
    }
    if entry_index is not None:
        evidence["entry_index"] = entry_index
    return evidence


# ═══════════════════════════════════════════════════════════════════
# 诊断报告生成
# ═══════════════════════════════════════════════════════════════════

def build_subscription_report(
    messages: list[dict[str, Any]],
    registry: Any,
    *,
    records: dict[str, Any] | None = None,
    notifications: dict[tuple[int, int], Any] | None = None,
) -> dict[str, Any]:
    """生成订阅诊断报告。

    以 Service → EventGroup 为主线，每条记录标注：
    - 服务端 ECU（Offer 方）
    - 客户端 ECU（Subscribe 方）
    - Offer → Subscribe → Notification 链路状态

    ``records`` 和 ``notifications`` 由统一查询层传入时，本函数不会再次
    遍历完整消息；保留 ``messages`` 参数是为了兼容原有命令行和测试入口。
    """
    if records is None:
        records = extract_sd_records(messages)

    # 索引
    offers_by_srv: dict[int, list[dict]] = defaultdict(list)
    for o in records["offers"]:
        offers_by_srv[o["service_id"]].append(o)

    subs_by_srv_eg: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for s in records["subscribes"]:
        subs_by_srv_eg[(s["service_id"], s["eventgroup_id"])].append(s)

    acks_by_srv_eg: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for a in records["subscribe_acks"]:
        acks_by_srv_eg[(a["service_id"], a["eventgroup_id"])].append(a)

    nacks_by_srv_eg: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for nack in records["subscribe_nacks"]:
        nacks_by_srv_eg[(nack["service_id"], nack["eventgroup_id"])].append(nack)

    # Notification 证据索引。后续按 EventGroup 关联并且只统计首次订阅后的通知。
    if notifications is None:
        notification_lists: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        for msg in messages:
            h = msg.get("header", {})
            sid = h.get("service_id", {}).get("dec", 0)
            mt = h.get("message_type", {}).get("dec", 0)
            if sid == _SD_SERVICE_ID or not is_notification(mt):
                continue
            mid = h.get("method_id", {}).get("dec", 0)
            notification_lists[(sid, mid)].append(build_message_evidence(
                msg,
                kind="Notification",
            ))
        notifications = notification_lists

    # 构建报告
    all_srv_ids: set[int] = set(offers_by_srv.keys()) | {k[0] for k in subs_by_srv_eg.keys()}
    services: list[dict[str, Any]] = []
    # 字段名必须同时表达统计对象和异常含义，防止模型混淆“服务数”和“事件组数”。
    summary = {
        "service_count": 0,
        "offered_service_count": 0,
        "observed_subscription_eventgroup_count": 0,
        "offer_conflict_service_count": 0,
        "subscribed_without_notification_eventgroup_count": 0,
        "offered_without_subscriber_service_count": 0,
        "subscribed_without_offer_service_count": 0,
        "subscribed_without_ack_eventgroup_count": 0,
        "nacked_eventgroup_count": 0,
    }

    for srv_id in sorted(all_srv_ids):
        offers = offers_by_srv.get(srv_id, [])
        server_ecus = sorted(set(o["ecu"] for o in offers))
        has_offer = len(offers) > 0
        offers_by_instance: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for offer in offers:
            offers_by_instance[offer["instance_id"]].append(offer)
        offer_instances = []
        conflict_instance_ids = []
        for instance_id, instance_offers in sorted(offers_by_instance.items()):
            instance_servers = sorted(set(item["ecu"] for item in instance_offers))
            instance_conflict = len(instance_servers) > 1
            if instance_conflict:
                conflict_instance_ids.append(instance_id)
            offer_instances.append({
                "instance_id": instance_id,
                "server_ecus": instance_servers,
                "offer_count": len(instance_offers),
                "offer_conflict": instance_conflict,
                "offer_evidence": _sample_evidence(instance_offers),
            })
        # Service ID 可部署多个 Instance；只有同一 Instance 被多个 ECU 发布才判为冲突。
        conflict = bool(conflict_instance_ids)

        svc: dict[str, Any] = {
            "service_id": srv_id,
            "service_id_hex": f"0x{srv_id:04X}",
            "service_name": _svc_name(registry, srv_id),
            "has_offer": has_offer,
            "server_ecus": server_ecus,
            "offer_conflict": conflict,
            "offer_count": len(offers),
            "instance_ids": sorted(set(o["instance_id"] for o in offers)),
            "offer_instances": offer_instances,
            "offer_conflict_instance_ids": conflict_instance_ids,
            "offer_evidence": _sample_evidence(offers),
            "eventgroups": [],
            "issues": [],
        }

        if conflict:
            conflict_labels = ", ".join(
                f"0x{instance_id:04X}" for instance_id in conflict_instance_ids
            )
            svc["issues"].append(
                f"Offer 冲突 — Instance {conflict_labels} 被多个 ECU 发布")
            summary["offer_conflict_service_count"] += 1

        # 收集 eventgroup
        eg_ids: set[int] = {eg for (sid, eg) in subs_by_srv_eg if sid == srv_id}

        if not has_offer and not eg_ids:
            continue

        summary["service_count"] += 1
        if has_offer:
            summary["offered_service_count"] += 1

        if not eg_ids:
            # 有 Offer 但无任何 Subscribe
            if has_offer:
                svc["issues"].append(
                    f"服务端 {', '.join(server_ecus)} 发布了 Offer，但无客户端 Subscribe")
                summary["offered_without_subscriber_service_count"] += 1
            services.append(svc)
            continue

        if not has_offer:
            svc["issues"].append("服务未被 Offer，但存在客户端 Subscribe")
            summary["subscribed_without_offer_service_count"] += 1

        for eg_id in sorted(eg_ids):
            subs = subs_by_srv_eg.get((srv_id, eg_id), [])
            acks = acks_by_srv_eg.get((srv_id, eg_id), [])
            nacks = nacks_by_srv_eg.get((srv_id, eg_id), [])
            client_ecus = sorted(set(s["ecu"] for s in subs))
            ack_ecus = sorted(set(a["ecu"] for a in acks))
            nack_ecus = sorted(set(nack["ecu"] for nack in nacks))

            # 使用 set 去重 ID。若 EventGroup 本身已带 0x8000，高位映射不能重复计数。
            notification_ids = {eg_id, eg_id | 0x8000}
            notification_evidence = [
                evidence
                for method_id in notification_ids
                for evidence in notifications.get((srv_id, method_id), [])
            ]
            if subs:
                first_subscribe_time = min(
                    float(s["evidence"].get("timestamp_epoch") or 0.0) for s in subs
                )
                notification_evidence = [
                    evidence for evidence in notification_evidence
                    if float(evidence.get("timestamp_epoch") or 0.0) >= first_subscribe_time
                ]
            notification_evidence.sort(
                key=lambda evidence: float(evidence.get("timestamp_epoch") or 0.0)
            )
            n_total = len(notification_evidence)

            eg: dict[str, Any] = {
                "eventgroup_id": eg_id,
                "event_name": _evt_name(registry, srv_id, eg_id),
                "eventgroup_name": _eg_name(registry, srv_id, eg_id),
                "server_ecus": server_ecus,
                "client_ecus": client_ecus,
                "ack_ecus": ack_ecus,
                "nack_ecus": nack_ecus,
                "subscribed": len(subs) > 0,
                "acked": len(acks) > 0,
                "nacked": len(nacks) > 0,
                "notification_count": n_total,
                "subscribe_count": len(subs),
                "ack_count": len(acks),
                "nack_count": len(nacks),
                "subscribe_evidence": _sample_evidence(subs),
                "ack_evidence": _sample_evidence(acks),
                "nack_evidence": _sample_evidence(nacks),
                "notification_evidence": _sample_evidence_values(notification_evidence),
                "issues": [],
            }

            # ---- 链路诊断 ----
            if eg["nacked"]:
                eg["issues"].append(
                    f"服务端 {', '.join(nack_ecus or server_ecus or ['未知'])} "
                    f"返回了 Subscribe Nack")
                summary["nacked_eventgroup_count"] += 1
            elif has_offer and eg["subscribed"] and not eg["acked"]:
                eg["issues"].append(
                    f"客户端 {', '.join(client_ecus)} Subscribe 了，"
                    f"但服务端 {', '.join(server_ecus)} 未 Ack")
                summary["subscribed_without_ack_eventgroup_count"] += 1
            elif has_offer and eg["subscribed"] and n_total == 0:
                eg["issues"].append(
                    f"服务端 {', '.join(server_ecus)} Offer ✓，"
                    f"客户端 {', '.join(client_ecus)} Subscribe ✓ → "
                    f"但未收到 Notification")
                summary["subscribed_without_notification_eventgroup_count"] += 1
            elif has_offer and not eg["subscribed"]:
                eg["issues"].append(
                    f"服务端 {', '.join(server_ecus)} Offer ✓，"
                    f"但无客户端 Subscribe")
            elif not has_offer and eg["subscribed"]:
                eg["issues"].append(
                    f"客户端 {', '.join(client_ecus)} Subscribe 了，"
                    f"但无服务端 Offer")

            svc["eventgroups"].append(eg)
            summary["observed_subscription_eventgroup_count"] += 1

        services.append(svc)

    return {"services": services, "summary": summary}


def _dec(val: Any) -> int:
    if isinstance(val, dict):
        return val.get("dec", 0)
    if isinstance(val, int):
        return val
    return 0


def _sample_evidence(records: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    """从生命周期记录中提取首尾证据，防止周期报文撑大 API 响应。"""
    return _sample_evidence_values(
        [record.get("evidence", {}) for record in records],
        limit=limit,
    )


def _sample_evidence_values(
    evidence: list[dict[str, Any]],
    limit: int = 12,
) -> list[dict[str, Any]]:
    """保留时间序列的首尾证据，中间重复项由数量字段表达。"""
    if len(evidence) <= limit:
        return evidence
    head_size = limit // 2
    return evidence[:head_size] + evidence[-(limit - head_size):]


def _svc_name(registry: Any, srv_id: int) -> str:
    try:
        n = registry.lookup_service_name(srv_id) if registry else None
        return n or ""
    except Exception:
        return ""


def _evt_name(registry: Any, srv_id: int, evt_id: int) -> str:
    try:
        if registry:
            n = registry.lookup_event_name(srv_id, evt_id)
            return n or ""
    except Exception:
        return ""


def _eg_name(registry: Any, srv_id: int, eg_id: int) -> str:
    try:
        if registry:
            n = registry.lookup_eventgroup_name(srv_id, eg_id)
            return n or ""
    except Exception:
        return ""
