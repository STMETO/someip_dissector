"""AI Tool 查询语义与白名单分发测试。"""
from __future__ import annotations

import unittest
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from someip.analysis.sd_diagnostic import build_subscription_report
from someip.analysis.queries import (
    ArxmlDefinitionQuery,
    MessageQuery,
    ensure_session_queries,
)
from someip.datatypes.types import BaseType, StringType, StructField, StructureType
from assistant.tools import TOOL_DEFINITIONS, execute_tool
from web.backend.handlers.analysis import _sessions, get_session
from web.backend.handlers.sd_diagnostic import get_subscription_report
from web.backend.handlers.signal_timing import get_signal_data, get_signal_meta

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

    def describe_service(self, service_id):
        """模拟注册表公开定义接口，供 ARXML Tool 测试。"""
        if service_id != 0x0A01:
            return None
        return {
            "service_id": service_id,
            "service_name": "ParkingService",
            "interface_ref": "/Services/ParkingService",
            "methods": [{
                "method_id": 1,
                "name": "SetParkingMode",
                "method_ref": "/Services/ParkingService/SetParkingMode",
                "arguments": [{
                    "name": "mode",
                    "direction": "IN",
                    "type_ref": "/Types/ParkingMode",
                }],
            }],
            "events": [{
                "event_id": 0x2005,
                "name": "ParkingState",
                "event_ref": "/Services/ParkingService/ParkingState",
                "type_ref": "/Types/ParkingState",
            }],
            "eventgroups": [{
                "eventgroup_id": 0xA005,
                "name": "ParkingEventGroup",
            }],
        }


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

    def test_fourteen_tools_are_registered(self):
        names = [item["function"]["name"] for item in TOOL_DEFINITIONS]
        self.assertEqual(names, [
            "get_subscription_status",
            "find_service",
            "get_offer_timeline",
            "get_subscription_timeline",
            "search_messages",
            "get_message_detail",
            "get_notification_statistics",
            "get_payload_field",
            "get_request_response_trace",
            "get_ecu_service_topology",
            "get_arxml_definition",
            "search_payload_values",
            "get_anomaly_details",
            "compare_sessions",
        ])

    def test_query_index_is_reused_by_page_and_ai(self):
        """页面和 Tool 必须复用同一查询对象，不能各自重建诊断结果。"""
        state = _sessions[_SESSION_ID]
        queries = ensure_session_queries(state)
        execute_tool("get_subscription_status", {}, _SESSION_ID)

        self.assertIs(ensure_session_queries(state), queries)
        self.assertIs(get_subscription_report(_SESSION_ID), queries.subscriptions.report())

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

    def test_notification_statistics_and_payload_field(self):
        statistics = execute_tool(
            "get_notification_statistics",
            {
                "service_id": "0x0A01",
                "method_id": "0xA005",
                "field_path": "status.speed",
            },
            _SESSION_ID,
        )
        field = execute_tool(
            "get_payload_field",
            {"message_index": 4, "field_path": "status.speed"},
            _SESSION_ID,
        )

        self.assertEqual(statistics["notification_count"], 1)
        self.assertEqual(statistics["events"][0]["field_statistics"]["average"], 42)
        self.assertEqual(field["field"]["value"], 42)
        self.assertEqual(field["evidence"]["frame_index"], 104)

    def test_signal_page_uses_unified_signal_query(self):
        meta = get_signal_meta(_SESSION_ID)
        series = get_signal_data(_SESSION_ID, 0x0A01, 0xA005, "status.speed")

        self.assertEqual(meta[0]["events"][0]["fields"], ["status.speed"])
        self.assertEqual(series["fields"][0]["points"][0]["value"], 42)

    def test_request_response_trace_matches_protocol_correlation_key(self):
        session_id = "request-response-tool-test"
        request = _message(20, 120, 0x0A01, 1, 0x00, "10.0.0.2", "10.0.0.1", "Request")
        response = _message(21, 121, 0x0A01, 1, 0x80, "10.0.0.1", "10.0.0.2", "Response")
        response["header"]["session_id"] = request["header"]["session_id"]
        response["timestamp_epoch"] = request["timestamp_epoch"] + 0.025
        missing = _message(22, 122, 0x0A01, 2, 0x00, "10.0.0.2", "10.0.0.1", "Request")
        _sessions[session_id] = _state(session_id, [request, response, missing])
        try:
            result = execute_tool("get_request_response_trace", {}, session_id)
            self.assertEqual(result["summary"]["status_counts"], {
                "matched": 1,
                "missing_response": 1,
            })
            self.assertEqual(result["traces"][0]["response_time_ms"], 25.0)
            self.assertEqual(result["traces"][0]["response_evidence"]["frame_index"], 121)
        finally:
            _sessions.pop(session_id, None)

    def test_ecu_topology_arxml_definition_and_payload_search(self):
        topology = execute_tool("get_ecu_service_topology", {}, _SESSION_ID)
        arxml = execute_tool(
            "get_arxml_definition",
            {"service_id": "0x0A01", "member_kind": "event"},
            _SESSION_ID,
        )
        payload = execute_tool(
            "search_payload_values",
            {
                "field_path": "status.speed",
                "service_id": "0x0A01",
                "minimum": 40,
                "maximum": 45,
            },
            _SESSION_ID,
        )

        by_ip = {row["ecu_ip"]: row for row in topology["ecus"]}
        self.assertIn("10.0.0.1", by_ip)
        self.assertIn("10.0.0.2", by_ip)
        self.assertNotIn("239.0.0.1", by_ip)
        self.assertEqual(by_ip["10.0.0.1"]["offered_services"][0]["service_id"], "0x0A01")
        self.assertTrue(arxml["found"])
        self.assertEqual(arxml["events"][0]["name"], "ParkingState")
        self.assertEqual(payload["matched_message_count"], 1)
        self.assertEqual(payload["matches"][0]["field"]["value"], 42)

    def test_arxml_definition_marks_offset_after_dynamic_field_unreliable(self):
        dynamic_text = StringType("Label", "/Types/Label")
        speed = BaseType("Speed", "/Types/Speed", bit_length=8)
        root = StructureType("ParkingState", "/Types/ParkingState")
        root.add_field(StructField("label", "/Types/Label", dynamic_text))
        root.add_field(StructField("speed", "/Types/Speed", speed))

        result = ArxmlDefinitionQuery(
            _Registry(),
            {"/Types/ParkingState": root},
        ).query(0x0A01, member_kind="event", field_path="speed")
        field = result["events"][0]["type_definition"]

        self.assertTrue(field["found"])
        self.assertIsNone(field["static_offset"])
        self.assertFalse(field["offset_reliable"])

    def test_anomaly_details_and_session_comparison_enforce_whitelist(self):
        target_session_id = "assistant-comparison-target"
        messages = _fixture_messages()[:-1]  # 去掉 Notification，形成订阅后无通知。
        _sessions[target_session_id] = _state(target_session_id, messages, pcap_name="target.pcap")
        try:
            anomaly = execute_tool(
                "get_anomaly_details",
                {"anomaly_type": "subscribed_without_notification"},
                target_session_id,
            )
            self.assertEqual(anomaly["summary"]["anomaly_count"], 1)
            self.assertEqual(anomaly["anomalies"][0]["eventgroup_id"], "0xA005")

            with self.assertRaisesRegex(ValueError, "未获得本轮访问授权"):
                execute_tool(
                    "compare_sessions",
                    {"session_ids": [target_session_id]},
                    _SESSION_ID,
                )
            comparison = execute_tool(
                "compare_sessions",
                {"session_ids": [target_session_id]},
                _SESSION_ID,
                {target_session_id},
            )
            delta = comparison["comparisons"][0]["notification_deltas"][0]
            self.assertEqual(delta["delta"], -1)
            self.assertEqual(
                comparison["comparisons"][0]["anomalies_added"][0]["anomaly_type"],
                "subscribed_without_notification",
            )
        finally:
            _sessions.pop(target_session_id, None)

    def test_non_monotonic_timestamps_fall_back_to_safe_filter(self):
        later = _message(20, 120, 0x0A01, 1, 0x02, "10.0.0.1", "10.0.0.2", "Notification")
        earlier = _message(21, 121, 0x0A01, 1, 0x02, "10.0.0.1", "10.0.0.2", "Notification")
        later["timestamp_epoch"] = 2000.0
        earlier["timestamp_epoch"] = 1000.0

        query = MessageQuery([later, earlier])
        result = query.search(start_time=1500.0)

        self.assertFalse(query.index_stats["time_ordered"])
        self.assertEqual(result.total, 1)
        self.assertEqual(result.messages[0]["index"], 20)

    def test_concurrent_session_restore_only_loads_disk_once(self):
        """页面并发请求消息、诊断和信号时，同一持久化会话只能恢复一次。"""
        session_id = "concurrent-session-load-test"
        loaded_state = SimpleNamespace(session_id=session_id)
        load_calls = []

        def fake_load(requested_id):
            load_calls.append(requested_id)
            time.sleep(0.02)
            return loaded_state

        try:
            with patch(
                "web.backend.handlers.analysis._load_session_from_disk",
                side_effect=fake_load,
            ):
                with ThreadPoolExecutor(max_workers=6) as executor:
                    states = list(executor.map(get_session, [session_id] * 6))
            self.assertTrue(all(state is loaded_state for state in states))
            self.assertEqual(load_calls, [session_id])
        finally:
            _sessions.pop(session_id, None)

    def test_unregistered_tool_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知工具"):
            execute_tool("run_shell", {}, _SESSION_ID)


def _state(
    session_id: str,
    messages: list[dict],
    *,
    pcap_name: str = "fixture.pcap",
) -> SimpleNamespace:
    """构造带完整查询依赖的轻量 Web 会话。"""
    return SimpleNamespace(
        session_id=session_id,
        session_dir=Path(f"/tmp/{session_id}"),
        messages=messages,
        registry=_Registry(),
        total_messages=len(messages),
        parsed_count=sum(message.get("parse_status") == "ok" for message in messages),
        pcap_name=pcap_name,
    )


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
    notification["parsed"] = {
        "name": "ParkingState",
        "type": "ParkingStateType",
        "kind": "container",
        "offset": 0,
        "byte_size": 1,
        "children": [{
            "name": "status",
            "type": "StatusType",
            "kind": "container",
            "offset": 0,
            "byte_size": 1,
            "children": [{
                "name": "speed",
                "type": "uint8",
                "kind": "leaf",
                "value": 42,
                "offset": 0,
                "byte_size": 1,
                "hex": "2a",
            }],
        }],
    }
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
