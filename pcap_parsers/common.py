from __future__ import annotations

from typing import Any, Literal, TypedDict

try:
    from typing import NotRequired  # Python >= 3.11
except ImportError:
    from typing_extensions import NotRequired  # Python < 3.11

from scapy.all import IP, TCP, UDP
from scapy.contrib.automotive.someip import SOMEIP


TransportName = Literal["UDP", "TCP"]


class HexIntDict(TypedDict):
    dec: int
    hex: str


class EndpointDict(TypedDict):
    src: str
    dst: str


class LayerEndpointsDict(TypedDict):
    src_ip: str | None
    dst_ip: str | None
    src_port: int
    dst_port: int
    endpoint: EndpointDict


class TpHeaderDict(TypedDict):
    offset: HexIntDict
    reserved: HexIntDict
    more_segments: HexIntDict


class HeaderDict(TypedDict):
    service_id: HexIntDict
    method_id: HexIntDict
    length: HexIntDict
    client_id: HexIntDict
    session_id: HexIntDict
    protocol_version: HexIntDict
    interface_version: HexIntDict
    message_type: HexIntDict
    return_code: HexIntDict
    tp: NotRequired[TpHeaderDict]


class MessageDict(LayerEndpointsDict):
    index: int
    frame_index: int
    transport: TransportName
    header: HeaderDict
    payload_hex: str
    payload_length: int
    raw_header_hex: str


class ErrorDict(LayerEndpointsDict):
    frame_index: int
    transport: TransportName
    type: str
    reason: str | list[str]
    raw_header_hex: NotRequired[str]
    transport_payload_length: NotRequired[int]


class ParsedByTransportDict(TypedDict):
    UDP: int
    TCP: int


class SummaryDict(TypedDict):
    total_frames: int
    udp_frames: int
    tcp_frames: int
    parsed_messages: int
    parsed_by_transport: ParsedByTransportDict
    error_count: int


class ParseResultDict(TypedDict):
    source_pcap: str
    output_json: str
    messages: list[MessageDict]
    errors: list[dict[str, Any]]
    summary: SummaryDict


VALID_MESSAGE_TYPES = {
    0x00, 0x01, 0x02,
    0x20, 0x21, 0x22,
    0x40, 0x41, 0x42,
    0x80, 0x81, 0x82,
    0xA0, 0xA1, 0xA2,
    0xC0, 0xC1, 0xC2,
}


def format_int(value: int, width: int) -> HexIntDict:
    return {
        "dec": value,
        "hex": f"0x{value:0{width}X}",
    }


def get_layer_endpoints(pkt, transport_layer) -> LayerEndpointsDict:
    ip_layer = pkt[IP] if pkt.haslayer(IP) else None
    src_ip = getattr(ip_layer, "src", None)
    dst_ip = getattr(ip_layer, "dst", None)
    src_port = transport_layer.sport
    dst_port = transport_layer.dport
    return {
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "src_port": src_port,
        "dst_port": dst_port,
        "endpoint": {
            "src": f"{src_ip}:{src_port}",
            "dst": f"{dst_ip}:{dst_port}",
        },
    }


def extract_someip_fields(someip_packet: SOMEIP) -> dict[str, Any]:
    return {field.name: someip_packet.getfieldval(field.name) for field in someip_packet.fields_desc}


def validate_someip(fields: dict[str, Any], payload_len: int) -> list[str]:
    errors = []
    proto_ver = fields.get("proto_ver")
    length = fields.get("len")
    msg_type = fields.get("msg_type")

    if proto_ver != 0x01:
        errors.append(f"protocol_version={proto_ver} is not standard SOME/IP value 1")

    if not isinstance(length, int):
        errors.append("length field is missing or not an integer")
    else:
        if length < 8:
            errors.append(f"length={length} is smaller than SOME/IP minimum 8")
        if 8 + length > payload_len:
            errors.append(
                f"length={length} implies total size {8 + length}, but transport payload is only {payload_len} bytes"
            )

    if msg_type not in VALID_MESSAGE_TYPES:
        errors.append(f"message_type=0x{msg_type:02X} is not a known SOME/IP type")

    return errors


def build_header_dict(fields: dict[str, Any]) -> HeaderDict:
    header = {
        "service_id": format_int(fields["srv_id"], 4),
        "method_id": format_int(fields["sub_id"], 4),
        "length": format_int(fields["len"], 8),
        "client_id": format_int(fields["client_id"], 4),
        "session_id": format_int(fields["session_id"], 4),
        "protocol_version": format_int(fields["proto_ver"], 2),
        "interface_version": format_int(fields["iface_ver"], 2),
        "message_type": format_int(fields["msg_type"], 2),
        "return_code": format_int(fields["retcode"], 2),
    }

    tp_fields = {
        "offset": fields.get("offset", 0),
        "reserved": fields.get("res", 0),
        "more_segments": fields.get("more_seg", 0),
    }
    if any(tp_fields.values()):
        header["tp"] = {
            "offset": format_int(tp_fields["offset"], 7),
            "reserved": format_int(tp_fields["reserved"], 1),
            "more_segments": format_int(tp_fields["more_segments"], 1),
        }

    return header


def build_message_dict(
    index: int,
    frame_index: int,
    transport: TransportName,
    pkt,
    fields: dict[str, Any],
    message_bytes: bytes,
) -> MessageDict:
    transport_layer = pkt[UDP] if transport == "UDP" else pkt[TCP]
    return {
        "index": index,
        "frame_index": frame_index,
        "transport": transport,
        **get_layer_endpoints(pkt, transport_layer),
        "header": build_header_dict(fields),
        "payload_hex": message_bytes[16:].hex(),
        "payload_length": len(message_bytes) - 16,
        "raw_header_hex": message_bytes[:16].hex(),
    }


def build_error_dict(
    frame_index: int,
    transport: TransportName,
    pkt,
    error_type: str,
    reason: str | list[str],
    raw_bytes: bytes | None = None,
) -> ErrorDict:
    transport_layer = pkt[UDP] if transport == "UDP" else pkt[TCP]
    error = {
        "frame_index": frame_index,
        "transport": transport,
        **get_layer_endpoints(pkt, transport_layer),
        "type": error_type,
        "reason": reason,
    }
    if raw_bytes is not None:
        error["raw_header_hex"] = raw_bytes[:16].hex()
        error["transport_payload_length"] = len(raw_bytes)
    return error