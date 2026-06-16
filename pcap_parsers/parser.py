from __future__ import annotations

import json
import sys
from pathlib import Path

from scapy.all import PcapReader, TCP, UDP

from common import ParseResultDict
from strategies import TcpSomeIpStrategy, TransportParseStrategy, UdpSomeIpStrategy

try:
    from utils.logger import get_logger
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from utils.logger import get_logger

logger = get_logger(__name__)


class SomeIpPcapParser:
    def __init__(self, strategies: list[TransportParseStrategy]):
        self.strategies = strategies

    def parse(self, pcap_path: Path, output_path: Path) -> ParseResultDict:
        logger.info("Parsing pcap: %s", pcap_path)
        # 初始化全局结果容器
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

        # 文件存在性校验
        if not pcap_path.exists():
            logger.warning("Pcap file not found: %s", pcap_path)
            result["errors"].append({
                "type": "FileNotFoundError",
                "reason": f"pcap file not found: {pcap_path}",
            })
            result["summary"]["error_count"] = 1
            return result

        # 报文索引
        message_index = 1

        # 流式读取 PCAP + 全局异常捕获
        try:
            with PcapReader(str(pcap_path)) as reader:  # Scapy 流式读取
                for frame_index, pkt in enumerate(reader, 1):   # enumerate(reader, 1)：帧号从 1 开始，和 Wireshark 帧编号对齐
                    result["summary"]["total_frames"] = frame_index

                    # 逐帧处理
                    if pkt.haslayer(UDP):
                        result["summary"]["udp_frames"] += 1
                    if pkt.haslayer(TCP):
                        result["summary"]["tcp_frames"] += 1

                    for strategy in self.strategies:
                        if not strategy.can_handle(pkt):
                            continue

                        parsed_messages, parsed_errors = strategy.extract_messages(frame_index, pkt)

                        for message in parsed_messages:
                            message["index"] = message_index    # 分配全局唯一自增序号
                            message_index += 1
                            result["messages"].append(message)  # 把这条合法报文存入全局总报文列表
                            result["summary"]["parsed_by_transport"][message["transport"]] += 1
                            logger.debug("Frame %d | %s message | SvcID=%s MethodID=%s",
                                         frame_index, message["transport"],
                                         message["header"]["service_id"]["hex"],
                                         message["header"]["method_id"]["hex"])

                        for err in parsed_errors:
                            logger.debug("Frame %d | %s error | %s: %s",
                                         frame_index, err["transport"], err["type"], err["reason"])

                        result["errors"].extend(parsed_errors)
                        break

                    # 每 1000 帧报告一次进度
                    if frame_index % 1000 == 0:
                        logger.debug("Frames processed: %d, messages found: %d",
                                     frame_index, message_index - 1)

        except Exception as exc:
            logger.error("Pcap read failed: %s", exc)
            result["errors"].append({
                "type": type(exc).__name__,
                "reason": str(exc),
            })

        result["summary"]["parsed_messages"] = len(result["messages"])
        result["summary"]["error_count"] = len(result["errors"])
        logger.info("Parse done — frames: %d, messages: %d, errors: %d",
                    result["summary"]["total_frames"],
                    result["summary"]["parsed_messages"],
                    result["summary"]["error_count"])
        return result


def parse_someip_pcap(pcap_path: Path, output_path: Path) -> ParseResultDict:
    # 实例化顶层 PCAP 解析调度器，先匹配 UDP，再匹配 TCP
    parser = SomeIpPcapParser([
        UdpSomeIpStrategy(),
        TcpSomeIpStrategy(),
    ])
    return parser.parse(pcap_path, output_path)

# 将解析完成的结构化结果字典 ParseResultDict，持久化写入本地 JSON 文件
def write_result_json(result: ParseResultDict, output_path: Path) -> None:
    logger.info("Writing result to: %s", output_path)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    logger.info("JSON written OK, size: %d bytes", output_path.stat().st_size)


def main() -> int:
    base_dir = Path(__file__).resolve().parent
    pcap_path = base_dir / "sample.pcap"
    output_path = base_dir / "sample.json"

    result = parse_someip_pcap(pcap_path, output_path)
    write_result_json(result, output_path)

    logger.info("Parsed messages: %d (UDP: %d, TCP: %d), Errors: %d",
                result["summary"]["parsed_messages"],
                result["summary"]["parsed_by_transport"]["UDP"],
                result["summary"]["parsed_by_transport"]["TCP"],
                result["summary"]["error_count"])

    if result["errors"] and not result["messages"]:
        logger.warning("All frames failed — check pcap format or SOME/IP configuration")
        return 1
    return 0