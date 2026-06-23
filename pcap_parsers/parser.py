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

        # ---- TP 分片重组（后处理） ----
        result["messages"], tp_errors = _reassemble_tp(result["messages"])
        result["errors"].extend(tp_errors)

        # 重新分配 index
        for i, msg in enumerate(result["messages"], 1):
            msg["index"] = i

        result["summary"]["parsed_messages"] = len(result["messages"])
        result["summary"]["error_count"] = len(result["errors"])
        logger.info("Parse done — frames: %d, messages: %d (after TP reassembly), errors: %d",
                    result["summary"]["total_frames"],
                    result["summary"]["parsed_messages"],
                    result["summary"]["error_count"])
        return result


# ---------------------------------------------------------------------------
# SOME/IP TP 分片重组
# ---------------------------------------------------------------------------

# TP 分片消息类型的 bit 5 为 1（0x20 掩码）
_TP_MASK = 0x20


def _reassemble_tp(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    """后处理：将 TP 分片报文重组为完整报文。

    Scapy 的 TP 字段解析有误，这里手动从 raw bytes 16-19 提取真实 offset/more_seg。
    TP 扩展头 4 字节在 payload_hex 前 8 个字符（4 bytes），真实 payload 从 byte 20 开始。
    """
    import struct

    # 分离 TP 和非 TP
    tp_msgs: list[dict] = []
    regular: list[dict] = []
    for m in messages:
        h = m.get("header", {})
        tp = h.get("tp")
        if tp and tp.get("offset", {}).get("dec", 0) >= 0:
            tp_msgs.append(m)
        else:
            regular.append(m)

    if not tp_msgs:
        return regular, []

    # 手动修正 TP 字段 + 剥离 TP 扩展头
    for m in tp_msgs:
        ph = m.get("payload_hex", "")
        if len(ph) >= 8:
            tp_word = struct.unpack(">I", bytes.fromhex(ph[:8]))[0]
            m["_real_offset"] = tp_word & 0x0FFFFFFF
            m["_real_more"] = (tp_word >> 31) & 0x1
            m["_real_payload_hex"] = ph[8:]  # 去掉 4-byte TP 扩展头
        else:
            m["_real_offset"] = m["header"]["tp"]["offset"]["dec"]
            m["_real_more"] = m["header"]["tp"]["more_segments"]["dec"]
            m["_real_payload_hex"] = ph

    # 分组
    groups: dict[tuple, list[dict]] = {}
    for m in tp_msgs:
        h = m["header"]
        key = (
            h["service_id"]["dec"],
            h["method_id"]["dec"],
            h.get("session_id", {}).get("dec", 0),
            h.get("client_id", {}).get("dec", 0),
            m.get("src_ip", ""),
            m.get("dst_ip", ""),
            m.get("src_port", 0),
            m.get("dst_port", 0),
        )
        groups.setdefault(key, []).append(m)

    errors: list[dict] = []
    reassembled: list[dict] = []

    for key, frags in groups.items():
        # 按真实 offset 排序
        frags.sort(key=lambda m: m["_real_offset"])

        # 按 offset 连续性拆分为多个 sub-sequence
        seqs = _split_tp_sequences(frags, key, errors)
        for seq in seqs:
            if not seq:
                continue

            # 未完成的序列 → 保留原分片
            if seq[-1].get("_real_more", 0) != 0:
                regular.extend(seq)
                continue

            # 拼接（使用剥离 TP 头的真实 payload）
            first = seq[0]
            payload_parts: list[bytes] = []
            for f in seq:
                rph = f.get("_real_payload_hex", f.get("payload_hex", ""))
                if rph:
                    payload_parts.append(bytes.fromhex(rph))

            full_payload = b"".join(payload_parts)
            base_msg_type = first["header"]["message_type"]["dec"] & ~_TP_MASK

            new_header = dict(first["header"])
            new_header["message_type"] = {
                "dec": base_msg_type,
                "hex": f"0x{base_msg_type:02X}",
            }
            new_header["length"] = {
                "dec": len(full_payload),
                "hex": f"0x{len(full_payload):08X}",
            }
            new_header.pop("tp", None)

            reassembled.append({
                "index": 0,
                "frame_index": first.get("frame_index", 0),
                "transport": first.get("transport", "UDP"),
                "src_ip": first.get("src_ip", ""),
                "dst_ip": first.get("dst_ip", ""),
                "src_port": first.get("src_port", 0),
                "dst_port": first.get("dst_port", 0),
                "endpoint": first.get("endpoint", {}),
                "header": new_header,
                "payload_hex": full_payload.hex(),
                "payload_length": len(full_payload),
                "raw_header_hex": first.get("raw_header_hex", ""),
            })

    # SD 后处理也要对重组后的消息做（在 parse 循环中已经对分片做过了，重组后需要重做）
    for m in reassembled:
        if m["header"]["service_id"]["dec"] == SOMEIP_SD_SERVICE_ID:
            sd_data = _parse_sd_payload(bytes.fromhex(m["payload_hex"]))
            if sd_data is not None:
                m["sd"] = sd_data

    return regular + reassembled, errors


def _split_tp_sequences(
    frags: list[dict], key: tuple, errors: list[dict]
) -> list[list[dict]]:
    """按 offset 连续性将分片拆为多个 sub-sequence。

    同一 key 下可能有多条 TP 消息交替分片；用多序列并行追踪，
    每条 fragment 匹配到已存在的 pending 序列或新建序列。
    """
    if not frags:
        return []

    frags.sort(key=lambda m: m.get("_real_offset", 0))
    pending: list[list[dict]] = []  # 并行追踪中的序列

    for f in frags:
        off = f.get("_real_offset", 0)
        matched = False

        # 尝试匹配到已有的 pending 序列
        for seq in pending:
            last = seq[-1]
            if last.get("_real_more", 0) == 0:
                continue
            # 计算该序列当前的 expected offset
            seq_expected = seq[0].get("_real_offset", 0) \
                + sum(len(fr.get("_real_payload_hex", fr.get("payload_hex", ""))) // 2
                      for fr in seq)
            if off == seq_expected:
                seq.append(f)
                matched = True
                break

        if not matched:
            pending.append([f])

    result: list[list[dict]] = []
    for seq in pending:
        if seq[-1].get("_real_more", 0) != 0:
            errors.append({
                "type": "tp_incomplete",
                "reason": f"TP incomplete: last fragment still has more_segments=1 for "
                          f"srv=0x{key[0]:04X} method=0x{key[1]:04X} session={key[2]}",
            })
        result.append(seq)

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


