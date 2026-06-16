from __future__ import annotations

 # Python 抽象基类工具，用来实现策略模式顶层抽象
from abc import ABC, abstractmethod     # ABC：所有抽象父类必须继承的基类；abstractmethod：标记抽象方法
from collections import defaultdict     # 带默认值的字典

from scapy.all import IP, TCP, UDP
from scapy.contrib.automotive.someip import SOMEIP

from .common import ErrorDict, MessageDict, build_error_dict, build_message_dict, extract_someip_fields, validate_someip
from utils.logger import get_logger

logger = get_logger(__name__)

# 策略模式（Strategy Pattern） 的抽象父类
# 统一 UDP、TCP 两种传输层 SOME/IP 报文的解析接口，对外提供完全一致的调用规范
class TransportParseStrategy(ABC):
    transport_name: str     # 子类必须赋值字符串标识传输层名称

    @abstractmethod
    def can_handle(self, pkt) -> bool:      # 判断当前 scapy 数据包 pkt 是否归当前策略处理
        raise NotImplementedError

    @abstractmethod     # 核心解析逻辑：对数据包执行完整 SOME/IP 解析，拆分出合法报文和解析异常报文
    def extract_messages(self, frame_index: int, pkt) -> tuple[list[MessageDict], list[ErrorDict]]:
        raise NotImplementedError

# 处理 UDP 承载的 SOME/IP 报文
class UdpSomeIpStrategy(TransportParseStrategy):
    transport_name = "UDP"

    def can_handle(self, pkt) -> bool:
        return pkt.haslayer(UDP)    #判断数据包是否包含 UDP 层

    def extract_messages(self, frame_index: int, pkt) -> tuple[list[MessageDict], list[ErrorDict]]:
        payload_bytes = bytes(pkt[UDP].payload) # 提取 UDP 载荷二进制
        if len(payload_bytes) < 16:     # 小于16字节不合法
            logger.debug("Frame %d | UDP payload too short (%d bytes), skipping",
                        frame_index, len(payload_bytes))
            return [], []

        try:    # Scapy 协议层解码，捕获解析异常
            someip_packet = SOMEIP(payload_bytes)
        except Exception as exc:
            logger.debug("Frame %d | UDP SOME/IP decode failed: %s", frame_index, exc)
            return [], [
                build_error_dict(frame_index, self.transport_name, pkt, type(exc).__name__, str(exc), payload_bytes)
            ]

        # 提取头部字段 + 业务合法性校验
        fields = extract_someip_fields(someip_packet)
        validation_errors = validate_someip(fields, len(payload_bytes))
        if validation_errors:
            logger.debug("Frame %d | UDP SOME/IP validation failed: %s",
                        frame_index, "; ".join(validation_errors))
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

        logger.debug("Frame %d | UDP SOME/IP OK | SvcID=0x%04X MethodID=0x%04X",
                     frame_index, fields["srv_id"], fields["sub_id"])
        return [build_message_dict(0, frame_index, self.transport_name, pkt, fields, payload_bytes)], []

# TCP 分片缓存工具
class TcpStreamReassembler:
    def __init__(self):
        # key：TCP 四元组 (源IP, 源端口, 目的IP, 目的端口)，区分双向独立 TCP 流
        # value：bytearray 二进制缓冲区，持续拼接同一条流的 TCP 分片载荷
        self._streams: dict[tuple, bytearray] = defaultdict(bytearray)

    @staticmethod
    def stream_key(pkt) -> tuple:   # 根据 Scapy 数据包提取四元组，作为每条 TCP 流唯一标识
        ip_layer = pkt[IP]
        tcp_layer = pkt[TCP]
        return ip_layer.src, tcp_layer.sport, ip_layer.dst, tcp_layer.dport

    # 取出当前 TCP 包的 payload 二进制,计算当前流的 key，把分片字节追加到对应流缓冲区；
    # 返回当前流完整缓存 buffer 给上层策略使用
    def append(self, pkt) -> bytearray | None:
        payload = bytes(pkt[TCP].payload)
        if not payload:
            return None

        key = self.stream_key(pkt)
        self._streams[key].extend(payload)
        logger.debug("TCP stream %s:%d→%s:%d | +%d bytes | buffer=%d bytes",
                     key[0], key[1], key[2], key[3], len(payload), len(self._streams[key]))
        return self._streams[key]


class TcpSomeIpStrategy(TransportParseStrategy):
    transport_name = "TCP"

    def __init__(self):
        self.reassembler = TcpStreamReassembler()

    def can_handle(self, pkt) -> bool:
        return pkt.haslayer(TCP)    # 判断数据包是否带 TCP 层

    def extract_messages(self, frame_index: int, pkt) -> tuple[list[MessageDict], list[ErrorDict]]:
        buffer = self.reassembler.append(pkt)   # 追加分片到缓存，判断是否有足够字节解析
        if buffer is None or len(buffer) < 16:
            return [], []

        messages = []
        errors = []

        while len(buffer) >= 16:    # 循环拆包（一条 TCP 流缓存里可能存在多条完整 SOME/IP 消息）
            header_bytes = bytes(buffer[:16])   # 仅截取前 16 字节解析 SOME/IP 标准头

            try:
                header_packet = SOMEIP(header_bytes)
            except Exception as exc:    # 头部二进制非法，整条流缓存清空，终止循环
                logger.debug("Frame %d | TCP header parse failed: %s", frame_index, exc)
                errors.append(
                    build_error_dict(frame_index, self.transport_name, pkt, type(exc).__name__, str(exc), header_bytes)
                )
                buffer.clear()
                break

            header_fields = extract_someip_fields(header_packet)
            if not isinstance(header_fields.get("len"), int):
                logger.debug("Frame %d | TCP length field missing/invalid, clearing buffer", frame_index)
                errors.append(      # length缺失/格式错误，清空缓存退出
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

            # 总长 = 头+len本身+len = 8 + len
            total_length = 8 + header_fields["len"]
            if total_length < 16:   # 不够长
                logger.debug("Frame %d | TCP invalid total_length=%d", frame_index, total_length)
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

            # 当前缓存字节不够一条完整 SOME/IP 消息，退出循环，等待下一个 TCP 分片。
            if len(buffer) < total_length:
                logger.debug("Frame %d | TCP waiting for more data: have %d, need %d",
                            frame_index, len(buffer), total_length)
                break

            # 截取完整报文，并从缓存删除已消费字节
            message_bytes = bytes(buffer[:total_length])
            del buffer[:total_length]

            # 完整报文全量解析 + 业务校验
            try:
                someip_packet = SOMEIP(message_bytes)
            except Exception as exc:
                logger.debug("Frame %d | TCP message parse failed: %s", frame_index, exc)
                errors.append(
                    build_error_dict(frame_index, self.transport_name, pkt, type(exc).__name__, str(exc), message_bytes)
                )
                continue    # 本条解析错误，后续继续解析

            fields = extract_someip_fields(someip_packet)
            validation_errors = validate_someip(fields, len(message_bytes))
            if validation_errors:
                logger.debug("Frame %d | TCP validation failed: %s",
                            frame_index, "; ".join(validation_errors))
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

            # 合法报文存入结果列表
            logger.debug("Frame %d | TCP SOME/IP OK | SvcID=0x%04X MethodID=0x%04X",
                         frame_index, fields["srv_id"], fields["sub_id"])
            messages.append(build_message_dict(0, frame_index, self.transport_name, pkt, fields, message_bytes))

        return messages, errors