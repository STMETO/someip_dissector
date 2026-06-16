from __future__ import annotations

from pathlib import Path
import json

from scapy.all import PcapReader, TCP, UDP

try:
    from .common import ParseResultDict
    from .strategies import TcpSomeIpStrategy, TransportParseStrategy, UdpSomeIpStrategy
except ImportError:
    from common import ParseResultDict
    from strategies import TcpSomeIpStrategy, TransportParseStrategy, UdpSomeIpStrategy


class SomeIpPcapParser:
    def __init__(self, strategies: list[TransportParseStrategy]):
        self.strategies = strategies

    def parse(self, pcap_path: Path, output_path: Path) -> ParseResultDict:
        result = {
            "source_pcap": str(pcap_path),
            "output_json": str(output_path),
            "messages": [],
            "errors": [],
            "summary": {
                "total_frames": 0,
                "udp_frames": 0,
                "tcp_frames": 0,
                "parsed_messages": 0,
                "parsed_by_transport": {
                    "UDP": 0,
                    "TCP": 0,
                },
                "error_count": 0,
            },
        }

        if not pcap_path.exists():
            result["errors"].append({
                "type": "FileNotFoundError",
                "reason": f"pcap file not found: {pcap_path}",
            })
            result["summary"]["error_count"] = 1
            return result

        message_index = 1

        try:
            with PcapReader(str(pcap_path)) as reader:
                for frame_index, pkt in enumerate(reader, 1):
                    result["summary"]["total_frames"] = frame_index

                    if pkt.haslayer(UDP):
                        result["summary"]["udp_frames"] += 1
                    if pkt.haslayer(TCP):
                        result["summary"]["tcp_frames"] += 1

                    for strategy in self.strategies:
                        if not strategy.can_handle(pkt):
                            continue

                        parsed_messages, parsed_errors = strategy.extract_messages(frame_index, pkt)

                        for message in parsed_messages:
                            message["index"] = message_index
                            message_index += 1
                            result["messages"].append(message)
                            result["summary"]["parsed_by_transport"][message["transport"]] += 1

                        result["errors"].extend(parsed_errors)
                        break

        except Exception as exc:
            result["errors"].append({
                "type": type(exc).__name__,
                "reason": str(exc),
            })

        result["summary"]["parsed_messages"] = len(result["messages"])
        result["summary"]["error_count"] = len(result["errors"])
        return result


def parse_someip_pcap(pcap_path: Path, output_path: Path) -> ParseResultDict:
    parser = SomeIpPcapParser([
        UdpSomeIpStrategy(),
        TcpSomeIpStrategy(),
    ])
    return parser.parse(pcap_path, output_path)


def write_result_json(result: ParseResultDict, output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)


def main() -> int:
    base_dir = Path(__file__).resolve().parent
    pcap_path = base_dir / "sample.pcap"
    output_path = base_dir / "sample.json"

    result = parse_someip_pcap(pcap_path, output_path)
    write_result_json(result, output_path)

    print(f"Parsed messages: {result['summary']['parsed_messages']}")
    print(f"UDP messages: {result['summary']['parsed_by_transport']['UDP']}")
    print(f"TCP messages: {result['summary']['parsed_by_transport']['TCP']}")
    print(f"Errors: {result['summary']['error_count']}")
    print(f"JSON written to: {output_path}")

    if result["errors"] and not result["messages"]:
        return 1
    return 0