"""读取单条 SOME/IP 报文完整解析详情的 Tool。"""
from __future__ import annotations

import json
from typing import Any

from analysis.sd_diagnostic import build_message_evidence
from .support import (
    header_int,
    lookup_method_or_event_name,
    lookup_service_name,
    parse_bool,
    parse_int,
    require_queries,
)
from pcap_parsers.common import message_type_label

_MAX_PAYLOAD_HEX_CHARS = 65_536
_MAX_TREE_JSON_CHARS = 120_000

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_message_detail",
        "description": (
            "按消息索引读取 SOME/IP Header、SD Entry/Option、Payload 解析树和网络端点，"
            "适合解释某条具体报文。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message_index": {"type": "integer", "description": "必填消息索引，即消息列表中的 Index。"},
                "include_payload_hex": {"type": "boolean", "description": "是否返回原始 Payload hex，默认 false。"},
                "include_parsed_tree": {"type": "boolean", "description": "是否返回反序列化解析树，默认 true。"},
            },
            "required": ["message_index"],
            "additionalProperties": False,
        },
    },
}


def get_message_detail(
    session_id: str,
    message_index: Any,
    include_payload_hex: Any = False,
    include_parsed_tree: Any = True,
) -> dict[str, Any]:
    """读取一条报文并限制大字段长度，防止单条深层 Payload 占满模型上下文。"""
    state, queries = require_queries(session_id)
    index = int(parse_int(
        message_index,
        "message_index",
        required=True,
        minimum=0,
        maximum=100_000_000,
    ))
    with_payload = parse_bool(include_payload_hex, "include_payload_hex")
    with_tree = parse_bool(include_parsed_tree, "include_parsed_tree", default=True)
    # 报文索引在会话建立时已构建，这里是 O(1) 读取。
    message = queries.messages.get(index)
    if message is None:
        raise ValueError(f"消息索引 {index} 不存在")

    service_id = header_int(message, "service_id")
    method_id = header_int(message, "method_id")
    message_type = header_int(message, "message_type")
    payload_hex = str(message.get("payload_hex", ""))
    result: dict[str, Any] = {
        "evidence": build_message_evidence(message),
        "transport": message.get("transport"),
        "endpoint": message.get("endpoint"),
        "header": message.get("header", {}),
        "service_name": lookup_service_name(state.registry, service_id),
        "method_or_event_name": lookup_method_or_event_name(
            state.registry, service_id, method_id
        ),
        "message_type_name": message.get("message_kind") or message_type_label(message_type),
        "parse_status": message.get("parse_status", "unresolved"),
        "raw_header_hex": message.get("raw_header_hex", ""),
        "payload": {
            "length_bytes": int(message.get("payload_length", len(payload_hex) // 2)),
            "hex_included": with_payload,
        },
        "sd": message.get("sd"),
    }

    if with_payload:
        result["payload"]["hex"] = payload_hex[:_MAX_PAYLOAD_HEX_CHARS]
        result["payload"]["hex_truncated"] = len(payload_hex) > _MAX_PAYLOAD_HEX_CHARS

    if with_tree:
        parsed_tree = message.get("parsed")
        result["parsed_tree"] = _bounded_json_value(parsed_tree)
    return result


def _bounded_json_value(value: Any) -> Any:
    """保留完整小树；超限时返回明确标记，要求模型缩小查询范围。"""
    if value is None:
        return None
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(serialized) <= _MAX_TREE_JSON_CHARS:
        return value
    return {
        "truncated": True,
        "original_json_char_count": len(serialized),
        "reason": "解析树超过单次 Tool 上下文限制，请通过报文页面查看完整树",
    }


__all__ = ["TOOL_DEFINITION", "get_message_detail"]
