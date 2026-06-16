from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scapy.all import PcapReader, TCP, UDP

from .common import (
    ParseResultDict,
    SD_ENTRY_TYPE_NAMES,
    SD_L4_PROTO_NAMES,
    SD_OPTION_TYPE_NAMES,
    SOMEIP_SD_SERVICE_ID,
    format_int,
)
from .strategies import TcpSomeIpStrategy, TransportParseStrategy, UdpSomeIpStrategy
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

                            # ---- SOME/IP-SD 后处理 ----
                            if message["header"]["service_id"]["dec"] == SOMEIP_SD_SERVICE_ID:
                                sd_data = _parse_sd_payload(bytes.fromhex(message["payload_hex"]))
                                if sd_data is not None:
                                    message["sd"] = sd_data

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


# ---------------------------------------------------------------------------
# SOME/IP-SD 负载解析
# ---------------------------------------------------------------------------

def _parse_sd_payload(payload_bytes: bytes) -> dict[str, Any] | None:
    """解析 SOME/IP-SD 负载，失败返回 None。

    仅在 Service ID == 0xFFFF 时由 _do_sd_postprocess 调用。
    依赖 .common 中的 SD_* 映射表。
    """
    try:
        from scapy.contrib.automotive.someip import SD  # noqa: PLC0415
        sd = SD(payload_bytes)
    except Exception:
        logger.debug("SD parse failed: payload=%s", payload_bytes.hex())
        return None

    # ---- 标志位 ----
    flags_raw = int(sd.flags)
    flag_names = []
    if flags_raw & 0x80:
        flag_names.append("Reboot")
    if flags_raw & 0x40:
        flag_names.append("Unicast")
    if flags_raw & 0x20:
        flag_names.append("Multicast")
    if not flag_names:
        flag_names.append("None")

    result: dict[str, Any] = {
        "flags": {
            "dec": flags_raw,
            "hex": f"0x{flags_raw:02X}",
            "names": flag_names,
        },
        "entries": [],
        "options": [],
    }

    # ---- Entry ----
    for entry in sd.entry_array:
        etype = int(getattr(entry, "type", 0))
        ed: dict[str, Any] = {
            "type": SD_ENTRY_TYPE_NAMES.get(etype, f"Unknown(0x{etype:02X})"),
        }
        if hasattr(entry, "srv_id"):
            ed["service_id"] = format_int(int(entry.srv_id), 4)
        if hasattr(entry, "inst_id"):
            ed["instance_id"] = format_int(int(entry.inst_id), 4)
        if hasattr(entry, "major_ver"):
            ed["major_version"] = format_int(int(entry.major_ver), 2)
        if hasattr(entry, "ttl"):
            ed["ttl"] = format_int(int(entry.ttl), 6)
        if hasattr(entry, "minor_ver"):
            ed["minor_version"] = format_int(int(entry.minor_ver), 8)
        if hasattr(entry, "eventgroup_id"):
            ed["eventgroup_id"] = format_int(int(entry.eventgroup_id), 4)
        result["entries"].append(ed)

    # ---- Option ----
    for opt in sd.option_array:
        otype = int(getattr(opt, "type", 0))
        od: dict[str, Any] = {
            "type": SD_OPTION_TYPE_NAMES.get(otype, f"Unknown(0x{otype:02X})"),
        }
        if hasattr(opt, "addr"):
            od["address"] = str(opt.addr)
        if hasattr(opt, "port"):
            od["port"] = int(opt.port)
        if hasattr(opt, "l4_proto"):
            proto_val = int(opt.l4_proto)
            od["l4_proto"] = SD_L4_PROTO_NAMES.get(proto_val, str(proto_val))
        if hasattr(opt, "priority"):
            od["priority"] = format_int(int(opt.priority), 2)
        if hasattr(opt, "weight"):
            od["weight"] = format_int(int(opt.weight), 2)
        result["options"].append(od)

    logger.debug("SD: %d entries, %d options",
                 len(result["entries"]), len(result["options"]))
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


