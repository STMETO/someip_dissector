"""AI Tool 查询语义与白名单分发测试。"""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from analysis.sd_diagnostic import build_subscription_report
from assistant.tools import TOOL_DEFINITIONS, execute_tool
from web.backend.handlers.analysis import _sessions

_SESSION_ID = "assistant-tool-test"


class _Registry:
    """提供测试所需的最小 ARXML 注册表接口。"""

    def list_services(self):
        return [(0x0A01, "ParkingService")]

    def lookup_service_name(self, service_id):
        return "ParkingService" if service_id == 0x0A01 else None

    def lookup_event_name(self, service_id, event_id):
        return "ParkingState" if (service_id, event_id) == (0x0A01, 0x2005) else None

    def lookup_method_name(self, _service_id, _method_id):
        return None

    def lookup_eventgroup_name(self, service_id, eventgroup_id):
        return "ParkingEventGroup" if (service_id, eventgroup_id) == (0x0A01, 0xA005) else None


class AssistantToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        messages = _fixture_messages()
        _sessions[_SESSION_ID] = SimpleNamespace(
            session_id=_SESSION_ID,
            session_dir=Path("/tmp/assistant-tool-test"),
            messages=messages,
            registry=_Registry(),
            total_messages=len(messages),
            pcap_name="fixture.pcap",
        )

    @classmethod
    def tearDownClass(cls):
        _sessions.pop(_SESSION_ID, None)

    def test_six_tools_are_registered(self):
        names = [item["function"]["name"] for item in TOOL_DEFINITIONS]
        self.assertEqual(names, [
            "get_subscription_status",
            "find_service",
            "get_offer_timeline",
            "get_subscription_timeline",
            "search_messages",
            "get_message_detail",
        ])

    def test_subscription_status_does_not_double_count_high_bit_eventgroup(self):
        result = execute_tool("get_subscription_status", {}, _SESSION_ID)
        eventgroup = result["services"][0]["eventgroups"][0]

        self.assertEqual(result["summary"]["service_count"], 1)
        self.assertEqual(eventgroup["eventgroup_id"], "0xA005")
        self.assertEqual(eventgroup["notification_count"], 1)
        self.assertEqual(eventgroup["notification_evidence"][0]["message_index"], 4)

    def test_different_instances_from_different_ecus_are_not_offer_conflict(self):
        first = _message(10, 110, 0xFFFF, 0x8100, 0x02, "10.0.0.1", "239.0.0.1", "Offer")
        first["sd"] = {"entries": [_entry("OfferService", ttl=5, instance_id=1)]}
        second = _message(11, 111, 0xFFFF, 0x8100, 0x02, "10.0.0.3", "239.0.0.1", "Offer")
        second["sd"] = {"entries": [_entry("OfferService", ttl=5, instance_id=2)]}

        service = build_subscription_report([first, second], _Registry())["services"][0]

        self.assertFalse(service["offer_conflict"])
        self.assertEqual(service["offer_conflict_instance_ids"], [])
        self.assertEqual(
            [(row["instance_id"], row["server_ecus"]) for row in service["offer_instances"]],
            [(1, ["10.0.0.1"]), (2, ["10.0.0.3"])],
        )

    def test_find_service_supports_name_and_leading_zero_decimal(self):
        by_name = execute_tool("find_service", {"query": "parking"}, _SESSION_ID)
        by_decimal = execute_tool("find_service", {"query": "02561"}, _SESSION_ID)

        self.assertEqual(by_name["services"][0]["service_id"], "0x0A01")
        self.assertEqual(by_decimal["services"][0]["service_id"], "0x0A01")

    def test_offer_and_subscription_timeline_return_evidence(self):
        offer = execute_tool(
            "get_offer_timeline", {"service_id": "0x0A01"}, _SESSION_ID
        )
        subscription = execute_tool(
            "get_subscription_timeline",
            {"service_id": "0x0A01", "eventgroup_id": "0xA005"},
            _SESSION_ID,
        )

        self.assertEqual(offer["summary"]["offer_message_count"], 1)
        self.assertEqual(offer["events"][0]["evidence"]["frame_index"], 101)
        self.assertEqual(subscription["summary"]["action_counts"], {
            "SubscribeEventGroup": 1,
            "SubscribeEventGroupAck": 1,
            "Notification": 1,
        })

    def test_message_search_and_detail(self):
        search = execute_tool(
            "search_messages",
            {"service_id": "0x0A01", "sd_entry_type": "OfferService"},
            _SESSION_ID,
        )
        detail = execute_tool(
            "get_message_detail", {"message_index": 4}, _SESSION_ID
        )

        self.assertEqual(search["matched_message_count"], 1)
        self.assertEqual(search["messages"][0]["sd_entries"][0]["service_id"], "0x0A01")
        self.assertEqual(detail["method_or_event_name"], "ParkingState")
        self.assertEqual(detail["parsed_tree"]["name"], "ParkingState")
        self.assertNotIn("hex", detail["payload"])

    def test_unregistered_tool_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知工具"):
            execute_tool("run_shell", {}, _SESSION_ID)


def _fixture_messages() -> list[dict]:
    """构造一组完整的 Offer -> Subscribe -> Ack -> Notification 链路。"""
    offer = _message(1, 101, 0xFFFF, 0x8100, 0x02, "10.0.0.1", "239.0.0.1", "Offer")
    offer["parse_status"] = "sd"
    offer["sd"] = {"entries": [_entry("OfferService", ttl=5)]}

    subscribe = _message(2, 102, 0xFFFF, 0x8100, 0x02, "10.0.0.2", "10.0.0.1", "Subscribe")
    subscribe["parse_status"] = "sd"
    subscribe["sd"] = {"entries": [_entry("SubscribeEventGroup", ttl=5, eventgroup=0xA005)]}

    ack = _message(3, 103, 0xFFFF, 0x8100, 0x02, "10.0.0.1", "10.0.0.2", "SubscribeAck")
    ack["parse_status"] = "sd"
    ack["sd"] = {"entries": [_entry("SubscribeEventGroupAck", ttl=5, eventgroup=0xA005)]}

    notification = _message(
        4, 104, 0x0A01, 0xA005, 0x02, "10.0.0.1", "239.0.0.2", "Notification"
    )
    notification["parse_status"] = "ok"
    notification["parsed"] = {"name": "ParkingState", "value": 1}
    return [offer, subscribe, ack, notification]


def _entry(
    entry_type: str,
    *,
    ttl: int,
    eventgroup: int | None = None,
    instance_id: int = 1,
) -> dict:
    entry = {
        "type": entry_type,
        "service_id": _number(0x0A01, 4),
        "instance_id": _number(instance_id, 4),
        "major_version": _number(1, 2),
        "minor_version": _number(0, 8),
        "ttl": _number(ttl, 6),
    }
    if eventgroup is not None:
        entry["eventgroup_id"] = _number(eventgroup, 4)
    return entry


def _message(
    index: int,
    frame_index: int,
    service_id: int,
    method_id: int,
    message_type: int,
    src_ip: str,
    dst_ip: str,
    kind: str,
) -> dict:
    return {
        "index": index,
        "frame_index": frame_index,
        "timestamp_epoch": 1000.0 + index,
        "timestamp_iso": f"2026-01-01T00:00:0{index}Z",
        "transport": "UDP",
        "src_ip": src_ip,
        "src_port": 30490,
        "dst_ip": dst_ip,
        "dst_port": 30490,
        "endpoint": {"src": f"{src_ip}:30490", "dst": f"{dst_ip}:30490"},
        "header": {
            "service_id": _number(service_id, 4),
            "method_id": _number(method_id, 4),
            "length": _number(9, 8),
            "client_id": _number(1, 4),
            "session_id": _number(index, 4),
            "protocol_version": _number(1, 2),
            "interface_version": _number(1, 2),
            "message_type": _number(message_type, 2),
            "return_code": _number(0, 2),
        },
        "message_kind": kind,
        "payload_hex": "01",
        "payload_length": 1,
        "raw_header_hex": "00" * 16,
    }


def _number(value: int, width: int) -> dict:
    return {"dec": value, "hex": f"0x{value:0{width}X}"}


if __name__ == "__main__":
    unittest.main()
