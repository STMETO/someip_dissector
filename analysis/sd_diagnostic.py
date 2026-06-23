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
    """从 messages 中提取所有 SD 记录。"""
    offers: list[dict[str, Any]] = []
    subscribes: list[dict[str, Any]] = []
    subscribe_acks: list[dict[str, Any]] = []

    for msg in messages:
        sd = msg.get("sd")
        if not isinstance(sd, dict):
            continue
        src_ip = msg.get("src_ip", "?")

        for entry in sd.get("entries", []):
            etype = entry.get("type", "")
            srv_id = _dec(entry.get("service_id"))
            inst_id = _dec(entry.get("instance_id"))
            record = {
                "service_id": srv_id,
                "instance_id": inst_id,
                "ecu": src_ip,
                "ttl": _dec(entry.get("ttl")),
            }

            if etype == "OfferService":
                offers.append(record)
            elif etype == "SubscribeEventGroup":
                record["eventgroup_id"] = _dec(entry.get("eventgroup_id"))
                subscribes.append(record)
            elif etype in ("SubscribeEventGroupAck", "SubscribeEventgroupAck"):
                record["eventgroup_id"] = _dec(entry.get("eventgroup_id"))
                subscribe_acks.append(record)

    return {"offers": offers, "subscribes": subscribes, "subscribe_acks": subscribe_acks}


# ═══════════════════════════════════════════════════════════════════
# 诊断报告生成
# ═══════════════════════════════════════════════════════════════════

def build_subscription_report(
    messages: list[dict[str, Any]],
    registry: Any,
) -> dict[str, Any]:
    """生成订阅诊断报告。

    以 Service → EventGroup 为主线，每条记录标注：
    - 服务端 ECU（Offer 方）
    - 客户端 ECU（Subscribe 方）
    - Offer → Subscribe → Notification 链路状态
    """
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

    # Notification 计数
    notif_count: dict[tuple[int, int], int] = defaultdict(int)
    for msg in messages:
        h = msg.get("header", {})
        sid = h.get("service_id", {}).get("dec", 0)
        mt = h.get("message_type", {}).get("dec", 0)
        if sid == _SD_SERVICE_ID or not is_notification(mt):
            continue
        mid = h.get("method_id", {}).get("dec", 0)
        notif_count[(sid, mid)] += 1

    # 构建报告
    all_srv_ids: set[int] = set(offers_by_srv.keys()) | {k[0] for k in subs_by_srv_eg.keys()}
    services: list[dict[str, Any]] = []
    summary = {
        "total_services": 0, "offered_services": 0,
        "total_eventgroups": 0, "conflict_count": 0,
        "silent_count": 0, "unsubscribed_count": 0, "no_offer_count": 0,
    }

    for srv_id in sorted(all_srv_ids):
        offers = offers_by_srv.get(srv_id, [])
        server_ecus = sorted(set(o["ecu"] for o in offers))
        has_offer = len(offers) > 0
        conflict = len(server_ecus) > 1

        svc: dict[str, Any] = {
            "service_id": srv_id,
            "service_id_hex": f"0x{srv_id:04X}",
            "service_name": _svc_name(registry, srv_id),
            "has_offer": has_offer,
            "server_ecus": server_ecus,
            "offer_conflict": conflict,
            "eventgroups": [],
            "issues": [],
        }

        if conflict:
            svc["issues"].append(
                f"Offer 冲突 — 多个 ECU 发布了同一服务: {', '.join(server_ecus)}")
            summary["conflict_count"] += 1

        # 收集 eventgroup
        eg_ids: set[int] = {eg for (sid, eg) in subs_by_srv_eg if sid == srv_id}

        if not has_offer and not eg_ids:
            continue

        summary["total_services"] += 1
        if has_offer:
            summary["offered_services"] += 1

        if not eg_ids:
            # 有 Offer 但无任何 Subscribe
            if has_offer:
                svc["issues"].append(
                    f"服务端 {', '.join(server_ecus)} 发布了 Offer，但无客户端 Subscribe")
                summary["unsubscribed_count"] += 1
            services.append(svc)
            continue

        if not has_offer:
            svc["issues"].append("服务未被 Offer，但存在客户端 Subscribe")
            summary["no_offer_count"] += 1

        for eg_id in sorted(eg_ids):
            subs = subs_by_srv_eg.get((srv_id, eg_id), [])
            acks = acks_by_srv_eg.get((srv_id, eg_id), [])
            client_ecus = sorted(set(s["ecu"] for s in subs))
            ack_ecus = sorted(set(a["ecu"] for a in acks))

            # Notification 计数（带/不带 0x8000 掩码）
            n_total = notif_count.get((srv_id, eg_id), 0) \
                      + notif_count.get((srv_id, eg_id | 0x8000), 0)

            eg: dict[str, Any] = {
                "eventgroup_id": eg_id,
                "event_name": _evt_name(registry, srv_id, eg_id),
                "eventgroup_name": _eg_name(registry, srv_id, eg_id),
                "server_ecus": server_ecus,
                "client_ecus": client_ecus,
                "ack_ecus": ack_ecus,
                "subscribed": len(subs) > 0,
                "acked": len(acks) > 0,
                "notification_count": n_total,
                "issues": [],
            }

            # ---- 链路诊断 ----
            if has_offer and eg["subscribed"] and not eg["acked"]:
                eg["issues"].append(
                    f"客户端 {', '.join(client_ecus)} Subscribe 了，"
                    f"但服务端 {', '.join(server_ecus)} 未 Ack")
            elif has_offer and eg["subscribed"] and n_total == 0:
                eg["issues"].append(
                    f"服务端 {', '.join(server_ecus)} Offer ✓，"
                    f"客户端 {', '.join(client_ecus)} Subscribe ✓ → "
                    f"但未收到 Notification")
                summary["silent_count"] += 1
            elif has_offer and not eg["subscribed"]:
                eg["issues"].append(
                    f"服务端 {', '.join(server_ecus)} Offer ✓，"
                    f"但无客户端 Subscribe")
                summary["unsubscribed_count"] += 1
            elif not has_offer and eg["subscribed"]:
                eg["issues"].append(
                    f"客户端 {', '.join(client_ecus)} Subscribe 了，"
                    f"但无服务端 Offer")
                summary["no_offer_count"] += 1

            svc["eventgroups"].append(eg)
            summary["total_eventgroups"] += 1

        services.append(svc)

    return {"services": services, "summary": summary}


def _dec(val: Any) -> int:
    if isinstance(val, dict):
        return val.get("dec", 0)
    if isinstance(val, int):
        return val
    return 0


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
