"""AI Tool 结果到前端证据导航参数的转换测试。"""
from __future__ import annotations

import unittest

from assistant.answering.navigation import (
    collect_navigation_links,
    collect_verified_navigation_links,
    validate_answer_navigation_links,
)


class NavigationLinkTests(unittest.TestCase):
    def test_extracts_nested_message_service_and_eventgroup_links(self):
        """嵌套 Tool 结果也必须稳定提取，不依赖模型回答的 Markdown 文案。"""
        links = collect_navigation_links(
            "get_subscription_status",
            {},
            {
                "services": [{
                    "service_id": "0x0A01",
                    "eventgroups": [{
                        "eventgroup_id": "0xA005",
                        "evidence": {
                            "message_index": 4,
                            "frame_index": 104,
                        },
                    }],
                }],
            },
        )

        self.assertIn({
            "kind": "message",
            "label": "Message 4 / Frame 104",
            "message_index": 4,
            "frame_index": 104,
        }, links)
        self.assertIn({
            "kind": "service",
            "label": "Service 0x0A01",
            "service_id": 0x0A01,
        }, links)
        self.assertIn({
            "kind": "eventgroup",
            "label": "EventGroup 0xA005",
            "service_id": 0x0A01,
            "eventgroup_id": 0xA005,
        }, links)

    def test_argument_ids_and_signal_time_range_are_preserved(self):
        links = collect_navigation_links(
            "get_notification_statistics",
            {
                "service_id": "02561",
                "method_id": "0xA005",
                "field_path": "status.speed",
                "start_time": "1.25",
                "end_time": 2.5,
            },
            {"events": []},
        )

        signal = next(item for item in links if item["kind"] == "signal")
        self.assertEqual(signal["service_id"], 0x0A01)
        self.assertEqual(signal["event_id"], 0xA005)
        self.assertEqual(signal["field_path"], "status.speed")
        self.assertEqual((signal["start_time"], signal["end_time"]), (1.25, 2.5))

    def test_signal_link_falls_back_to_eventgroup_when_method_is_empty(self):
        links = collect_navigation_links(
            "get_subscription_timeline",
            {
                "service_id": "0x0A01",
                "method_id": None,
                "eventgroup_id": "0xA005",
                "start_time": 1,
                "end_time": 2,
            },
            {},
        )

        signal = next(item for item in links if item["kind"] == "signal")
        self.assertEqual(signal["event_id"], 0xA005)

    def test_message_links_are_deduplicated_and_bounded(self):
        rows = [
            {"message_index": index, "frame_index": index + 100}
            for index in range(12)
        ]
        rows.append({"message_index": 0, "frame_index": 100})

        links = collect_navigation_links("search_messages", {}, {"messages": rows})
        message_links = [item for item in links if item["kind"] == "message"]

        self.assertEqual(len(message_links), 8)
        self.assertEqual([item["message_index"] for item in message_links], list(range(8)))

    def test_explicit_service_filter_excludes_other_sd_entries(self):
        """一条 SD 报文可能含多个 Entry，证据区只展示用户明确查询的 Service。"""
        links = collect_navigation_links(
            "search_messages",
            {"service_id": "0x0A01"},
            {
                "messages": [{
                    "message_index": 1,
                    "sd_entries": [
                        {"service_id": "0x0A01"},
                        {"service_id": "0x0010"},
                    ],
                }],
            },
        )

        service_ids = [item["service_id"] for item in links if item["kind"] == "service"]
        self.assertEqual(service_ids, [0x0A01])

    def test_verified_links_do_not_trust_argument_only_service(self):
        links = collect_verified_navigation_links(
            "search_messages",
            {"service_id": "0x0A01"},
            {"messages": []},
        )

        self.assertFalse(any(item["kind"] == "service" for item in links))

    def test_cross_session_comparison_does_not_create_current_session_links(self):
        result = {
            "comparisons": [{
                "session_id": "target-session",
                "services_added": [{"service_id": "0x0A01"}],
                "evidence": {"message_index": 4, "frame_index": 104},
            }],
        }

        self.assertEqual(collect_navigation_links("compare_sessions", {}, result), [])
        self.assertEqual(
            collect_verified_navigation_links("compare_sessions", {}, result),
            [],
        )

    def test_answer_link_validator_keeps_only_verified_targets(self):
        answer = (
            "[Message 4](#someip-message-4) "
            "[Message 5](#someip-message-5) "
            "[docs](https://example.com)"
        )
        verified = [{"kind": "message", "message_index": 4}]

        sanitized, removed = validate_answer_navigation_links(answer, verified)

        self.assertIn("[Message 4](#someip-message-4)", sanitized)
        self.assertIn("Message 5", sanitized)
        self.assertNotIn("#someip-message-5", sanitized)
        self.assertIn("[docs](https://example.com)", sanitized)
        self.assertEqual(removed, 1)


if __name__ == "__main__":
    unittest.main()
