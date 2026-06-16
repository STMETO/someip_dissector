from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict

from scapy.all import IP, TCP, UDP
from scapy.contrib.automotive.someip import SOMEIP

try:
    from .common import ErrorDict, MessageDict, build_error_dict, build_message_dict, extract_someip_fields, validate_someip
except ImportError:
    from common import ErrorDict, MessageDict, build_error_dict, build_message_dict, extract_someip_fields, validate_someip


class TransportParseStrategy(ABC):
    transport_name: str

    @abstractmethod
    def can_handle(self, pkt) -> bool:
        raise NotImplementedError

    @abstractmethod
    def extract_messages(self, frame_index: int, pkt) -> tuple[list[MessageDict], list[ErrorDict]]:
        raise NotImplementedError


class UdpSomeIpStrategy(TransportParseStrategy):
    transport_name = "UDP"

    def can_handle(self, pkt) -> bool:
        return pkt.haslayer(UDP)

    def extract_messages(self, frame_index: int, pkt) -> tuple[list[MessageDict], list[ErrorDict]]:
        payload_bytes = bytes(pkt[UDP].payload)
        if len(payload_bytes) < 16:
            return [], []

        try:
            someip_packet = SOMEIP(payload_bytes)
        except Exception as exc:
            return [], [
                build_error_dict(frame_index, self.transport_name, pkt, type(exc).__name__, str(exc), payload_bytes)
            ]

        fields = extract_someip_fields(someip_packet)
        validation_errors = validate_someip(fields, len(payload_bytes))
        if validation_errors:
            return [], [
                build_error_dict(
                    frame_index,
                    self.transport_name,
                    pkt,
                    "InvalidSomeIpMessage",
                    validation_errors,
                    payload_bytes,
                )
            ]

        return [build_message_dict(0, frame_index, self.transport_name, pkt, fields, payload_bytes)], []


class TcpStreamReassembler:
    def __init__(self):
        self._streams: dict[tuple, bytearray] = defaultdict(bytearray)

    @staticmethod
    def stream_key(pkt) -> tuple:
        ip_layer = pkt[IP]
        tcp_layer = pkt[TCP]
        return ip_layer.src, tcp_layer.sport, ip_layer.dst, tcp_layer.dport

    def append(self, pkt) -> bytearray | None:
        payload = bytes(pkt[TCP].payload)
        if not payload:
            return None

        key = self.stream_key(pkt)
        self._streams[key].extend(payload)
        return self._streams[key]


class TcpSomeIpStrategy(TransportParseStrategy):
    transport_name = "TCP"

    def __init__(self):
        self.reassembler = TcpStreamReassembler()

    def can_handle(self, pkt) -> bool:
        return pkt.haslayer(TCP)

    def extract_messages(self, frame_index: int, pkt) -> tuple[list[MessageDict], list[ErrorDict]]:
        buffer = self.reassembler.append(pkt)
        if buffer is None or len(buffer) < 16:
            return [], []

        messages = []
        errors = []

        while len(buffer) >= 16:
            header_bytes = bytes(buffer[:16])

            try:
                header_packet = SOMEIP(header_bytes)
            except Exception as exc:
                errors.append(
                    build_error_dict(frame_index, self.transport_name, pkt, type(exc).__name__, str(exc), header_bytes)
                )
                buffer.clear()
                break

            header_fields = extract_someip_fields(header_packet)
            if not isinstance(header_fields.get("len"), int):
                errors.append(
                    build_error_dict(
                        frame_index,
                        self.transport_name,
                        pkt,
                        "InvalidSomeIpMessage",
                        ["length field is missing or not an integer"],
                        header_bytes,
                    )
                )
                buffer.clear()
                break

            total_length = 8 + header_fields["len"]
            if total_length < 16:
                errors.append(
                    build_error_dict(
                        frame_index,
                        self.transport_name,
                        pkt,
                        "InvalidSomeIpMessage",
                        [f"length={header_fields['len']} implies invalid total size {total_length}"],
                        header_bytes,
                    )
                )
                buffer.clear()
                break

            if len(buffer) < total_length:
                break

            message_bytes = bytes(buffer[:total_length])
            del buffer[:total_length]

            try:
                someip_packet = SOMEIP(message_bytes)
            except Exception as exc:
                errors.append(
                    build_error_dict(frame_index, self.transport_name, pkt, type(exc).__name__, str(exc), message_bytes)
                )
                continue

            fields = extract_someip_fields(someip_packet)
            validation_errors = validate_someip(fields, len(message_bytes))
            if validation_errors:
                errors.append(
                    build_error_dict(
                        frame_index,
                        self.transport_name,
                        pkt,
                        "InvalidSomeIpMessage",
                        validation_errors,
                        message_bytes,
                    )
                )
                continue

            messages.append(build_message_dict(0, frame_index, self.transport_name, pkt, fields, message_bytes))

        return messages, errors