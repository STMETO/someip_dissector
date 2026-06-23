"""
SD 订阅诊断 — 纯后端逻辑。

分析会话中的 SD 报文（OfferService / SubscribeEventGroup），
结合 ARXML 事件注册表，生成订阅诊断报告。
不依赖 web / session，可直接被 handler 或 CLI 调用。
"""
from __future__ import annotations
from collections import defaultdict
from typing import Any

_SD_SERVICE_ID = 0xFFFF
_NOTIFICATION_TYPE = 0x02


# ═══════════════════════════════════════════════════════════════════
# SD 记录提取
# ═══════════════════════════════════════════════════════════════════

def extract_sd_records(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """从 messages 中提取所有 SD 记录。

    Returns
    -------
    {
        "offers":       [(srv_id, inst_id, ecu_ip, endpoint), ...],
        "subscribes":   [(srv_id, inst_id, eg_id, ecu_ip), ...],
        "subscribe_ack":[(srv_id, inst_id, eg_id, ecu_ip), ...],
        "endpoints":    {(srv_id, inst_id): [{"ip", "port", "proto"}, ...]}
    }
    """
    offers: list[dict[str, Any]] = []
    subscribes: list[dict[str, Any]] = []
    subscribe_acks: list[dict[str, Any]] = []
    endpoints: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)

    for msg in messages:
        sd = msg.get("sd")
        if not isinstance(sd, dict):
            continue

        src_ip = msg.get("src_ip", "?")
        opts = sd.get("options", [])

        for entry in sd.get("entries", []):
            etype = entry.get("type", "")
            srv_id = _dec(entry.get("service_id"))
            inst_id = _dec(entry.get("instance_id"))
            record = {
                "service_id": srv_id,
                "instance_id": inst_id,
                "ecu": src_ip,
                "ttl": _dec(entry.get("ttl")),
                "major_version": _dec(entry.get("major_version")),
            }

            if etype == "OfferService":
                offers.append(record)
                # 收集该 offer 对应的 endpoint
                key = (srv_id, inst_id)
                for opt in opts:
                    ep = {
                        "ip": opt.get("address", src_ip),
                        "port": opt.get("port", 0),
                        "proto": opt.get("l4_proto", "?"),
                    }
                    if ep not in endpoints[key]:
                        endpoints[key].append(ep)

            elif etype == "SubscribeEventGroup":
                record["eventgroup_id"] = _dec(entry.get("eventgroup_id"))
                subscribes.append(record)

            elif etype in ("SubscribeEventGroupAck", "SubscribeEventgroupAck"):
                record["eventgroup_id"] = _dec(entry.get("eventgroup_id"))
                subscribe_acks.append(record)

    return {
        "offers": offers,
        "subscribes": subscribes,
        "subscribe_acks": subscribe_acks,
        "endpoints": {f"{k[0]}_{k[1]}": v for k, v in endpoints.items()},
    }


# ═══════════════════════════════════════════════════════════════════
# 诊断报告生成
# ═══════════════════════════════════════════════════════════════════

def build_subscription_report(
    messages: list[dict[str, Any]],
    registry: Any,  # ServiceRegistry
) -> dict[str, Any]:
    """生成订阅诊断报告。

    检查项：
    - 服务是否被 Offer
    - Eventgroup 是否被 Subscribe
    - 实际收到多少 Notification
    - 是否存在多 ECU Offer 冲突
    """
    records = extract_sd_records(messages)

    # ---- 建立索引 ----
    # offers_by_srv[srv_id] = [offer_record, ...]
    offers_by_srv: dict[int, list[dict]] = defaultdict(list)
    for o in records["offers"]:
        offers_by_srv[o["service_id"]].append(o)

    # subs_by_srv_eg[(srv_id, eg_id)] = [sub_record, ...]
    subs_by_srv_eg: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for s in records["subscribes"]:
        subs_by_srv_eg[(s["service_id"], s["eventgroup_id"])].append(s)

    # acks_by_srv_eg[(srv_id, eg_id)] = [ack_record, ...]
    acks_by_srv_eg: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for a in records["subscribe_acks"]:
        acks_by_srv_eg[(a["service_id"], a["eventgroup_id"])].append(a)

    # ---- 统计 Notification 数量 ----
    # notif_count[(srv_id, method_id)] → count
    notif_count: dict[tuple[int, int], int] = defaultdict(int)
    for msg in messages:
        header = msg.get("header", {})
        srv_id = header.get("service_id", {}).get("dec", 0)
        msg_type = header.get("message_type", {}).get("dec", 0)
        if srv_id == _SD_SERVICE_ID or msg_type != _NOTIFICATION_TYPE:
            continue
        mid = header.get("method_id", {}).get("dec", 0)
        notif_count[(srv_id, mid)] += 1

    # ---- 构建报告 ----
    all_srv_ids: set[int] = set()
    all_srv_ids.update(offers_by_srv.keys())
    all_srv_ids.update(k[0] for k in subs_by_srv_eg.keys())

    services: list[dict[str, Any]] = []
    summary = {
        "total_services": 0,
        "offered_services": 0,
        "total_eventgroups": 0,
        "conflict_count": 0,
        "silent_count": 0,       # 有订阅但无通知
        "no_offer_count": 0,     # 有订阅但无 offer
    }

    for srv_id in sorted(all_srv_ids):
        offers = offers_by_srv.get(srv_id, [])
        srv_entry: dict[str, Any] = {
            "service_id": srv_id,
            "service_id_hex": f"0x{srv_id:04X}",
            "offers": offers,
            "has_offer": len(offers) > 0,
            "offer_conflict": len(set(o["ecu"] for o in offers)) > 1,
            "eventgroups": [],
            "issues": [],
        }

        if srv_entry["offer_conflict"]:
            srv_entry["issues"].append(f"多 ECU Offer 冲突: {', '.join(sorted(set(o['ecu'] for o in offers)))}")
            summary["conflict_count"] += 1

        # 收集该服务下所有被订阅的 eventgroup
        eg_ids: set[int] = set()
        for (sid, eg_id) in subs_by_srv_eg:
            if sid == srv_id:
                eg_ids.add(eg_id)

        if not eg_ids:
            # 无订阅：只记录 offer 情况
            if srv_entry["has_offer"]:
                summary["offered_services"] += 1
                summary["total_services"] += 1
            services.append(srv_entry)
            continue

        summary["total_services"] += 1
        if srv_entry["has_offer"]:
            summary["offered_services"] += 1
        else:
            srv_entry["issues"].append("无 Offer — 客户端订阅了但服务端未发布")
            summary["no_offer_count"] += 1

        for eg_id in sorted(eg_ids):
            subs = subs_by_srv_eg.get((srv_id, eg_id), [])
            acks = acks_by_srv_eg.get((srv_id, eg_id), [])
            subscriber_ecus = sorted(set(s["ecu"] for s in subs))
            ack_ecus = sorted(set(a["ecu"] for a in acks))

            # 统计该 eventgroup 对应的 notification 数量
            # eventgroup_id 对应部署中的 event_id
            total_notif = notif_count.get((srv_id, eg_id), 0)
            # 也尝试带 0x8000 掩码查找
            if total_notif == 0:
                total_notif = notif_count.get((srv_id, eg_id | 0x8000), 0)

            eg_entry: dict[str, Any] = {
                "eventgroup_id": eg_id,
                "subscribed": len(subs) > 0,
                "acked": len(acks) > 0,
                "subscriber_ecus": subscriber_ecus,
                "ack_ecus": ack_ecus,
                "notification_count": total_notif,
                "issues": [],
            }

            if not eg_entry["subscribed"]:
                eg_entry["issues"].append("未订阅")
            elif not eg_entry["acked"]:
                eg_entry["issues"].append("Subscribe 未被 Ack")
            elif total_notif == 0:
                eg_entry["issues"].append("已订阅但未收到 Notification 报文")
                summary["silent_count"] += 1

            # 尝试从 registry 查找事件名
            try:
                type_path = registry.lookup_event(srv_id, eg_id)
                if type_path is None:
                    type_path = registry.lookup_event(srv_id, eg_id | 0x8000)
                if type_path:
                    eg_entry["event_name"] = type_path.rsplit("/", 1)[-1]
            except Exception:
                pass

            srv_entry["eventgroups"].append(eg_entry)
            summary["total_eventgroups"] += 1

        services.append(srv_entry)

    return {
        "services": services,
        "summary": summary,
    }


def _dec(val: Any) -> int:
    """从 {dec, hex} 字典或直接 int 取值。"""
    if isinstance(val, dict):
        return val.get("dec", 0)
    if isinstance(val, int):
        return val
    return 0
