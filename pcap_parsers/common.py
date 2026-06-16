# 开启延迟类型注解，允许类型注解中使用尚未定义的类型，必须放在文件首行
from __future__ import annotations

from typing import Any, Literal, TypedDict  # 静态类型注解基础工具
# 兼容Python3.11前后TypedDict可选字段标记NotRequired
try:
    from typing import NotRequired
except ImportError:
    from typing_extensions import NotRequired

# Scapy内置网络分层协议类，用于解析IP、UDP、TCP报文
from scapy.all import IP, TCP, UDP
# Scapy汽车领域扩展模块，解析车载SOME/IP协议报文
from scapy.contrib.automotive.someip import SOMEIP

from utils.logger import get_logger

logger = get_logger(__name__)

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

# SOME/IP 分段传输（TP）扩展头字段
# 只有大包分片报文才会出现，普通报文没有，所以后面 HeaderDict 里 tp 标记为可选。
# offset 分片偏移、more_segments 是否还有后续分片。
class TpHeaderDict(TypedDict):
    offset: HexIntDict
    reserved: HexIntDict
    more_segments: HexIntDict

# 完整 SOME/IP 标准头部所有字段
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
    tp: NotRequired[TpHeaderDict]   # 可选

# 一条解析成功的 SOME/IP 报文完整数据
class MessageDict(LayerEndpointsDict):
    index: int
    frame_index: int
    transport: TransportName
    header: HeaderDict
    payload_hex: str        # 负载十六进制字符串
    payload_length: int    
    raw_header_hex: str     # 原始头部 16 字节十六进制

# 解析失败的异常报文记录
class ErrorDict(LayerEndpointsDict):
    frame_index: int
    transport: TransportName
    type: str
    reason: str | list[str]
    raw_header_hex: NotRequired[str]
    transport_payload_length: NotRequired[int]

# 统计区分 UDP、TCP 分别解析成功多少条报文
class ParsedByTransportDict(TypedDict):
    UDP: int
    TCP: int

# 全局统计汇总信息
class SummaryDict(TypedDict):
    total_frames: int
    udp_frames: int
    tcp_frames: int
    parsed_messages: int
    parsed_by_transport: ParsedByTransportDict
    error_count: int

# 整个 pcap 文件解析后的最终输出大结构体
class ParseResultDict(TypedDict):
    source_pcap: str
    output_json: str
    messages: list[MessageDict]
    errors: list[dict[str, Any]]
    summary: SummaryDict

# SOME/IP 协议规定合法的 message_type（消息类型）集合
VALID_MESSAGE_TYPES = {
    0x00, 0x01, 0x02,   # 请求类消息
    0x20, 0x21, 0x22,   # 响应类消息
    0x40, 0x41, 0x42,   # 错误响应
    0x80, 0x81, 0x82,   # 通知（Notification）
    0xA0, 0xA1, 0xA2,   # 事件（Event）
    0xC0, 0xC1, 0xC2,   # 字段（Field）
}

# 格式化数字，统一输出十进制 + 十六进制
# width：控制十六进制补 0 对齐（比如 width=4 → 0x0001，width=2 → 0x01）
def format_int(value: int, width: int) -> HexIntDict:
    return {
        "dec": value,
        "hex": f"0x{value:0{width}X}",
    }

# 提取 IP、端口四层端点信息
# pkt：完整 scapy 数据包
# transport_layer：当前包的 UDP 层或 TCP 层对象。
def get_layer_endpoints(pkt, transport_layer) -> LayerEndpointsDict:
    # 取数据包IP层，没有IP层就赋值None
    ip_layer = pkt[IP] if pkt.haslayer(IP) else None
    # 源IP、目的IP，无IP则为None
    src_ip = getattr(ip_layer, "src", None) # getattr(对象, 属性名, 取不到时的默认值)
    dst_ip = getattr(ip_layer, "dst", None)
    # 从UDP/TCP层拿源端口、目的端口
    src_port = transport_layer.sport
    dst_port = transport_layer.dport
    # 按照LayerEndpointsDict模板返回字典
    return {
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "src_port": src_port,
        "dst_port": dst_port,
        # 拼接成 IP:端口 格式字符串
        "endpoint": {
            "src": f"{src_ip}:{src_port}",
            "dst": f"{dst_ip}:{dst_port}",
        },
    }


# 遍历 Scapy 解析出的 SOMEIP 报文对象，
# 把所有协议头字段名 + 对应数值提取出来，组装成普通字典，方便后面校验、格式化输出。
# someip_packet: SOMEIP 入参是 Scapy 解析得到的 SOMEIP 层数据包对象。
# someip_packet.fields_desc : Scapy 协议层自带属性，存放当前协议全部字段定义列表，比如 service_id、method_id、len、msg_type、offset、more_seg 等所有 SOME/IP 头部字段。
def extract_someip_fields(someip_packet: SOMEIP) -> dict[str, Any]:
    #someip_packet.getfieldval(field.name)  Scapy 提供的方法，根据字段名取出该字段对应的原始数字值。
    return {field.name: someip_packet.getfieldval(field.name) for field in someip_packet.fields_desc}


# 对提取出来的 SOME/IP 头部字段做合法性校验，收集所有不规范、非法的报文问题，最后把所有错误描述以字符串列表返回；
# 列表为空代表报文合法，有内容就说明这条包异常，要存入 errors 错误日志。
# fields：extract_someip_fields 拿到的原生 SOMEIP 字段字典
# payload_len：UDP/TCP 传输层负载总字节长度（承载整个 SOMEIP 报文）
# 返回：list[str] 每条字符串是一条错误说明
def validate_someip(fields: dict[str, Any], payload_len: int) -> list[str]:
    errors = []
    # 取出三个核心校验字段
    proto_ver = fields.get("proto_ver")
    length = fields.get("len")
    msg_type = fields.get("msg_type")

    if proto_ver != 0x01:   # 协议版本必须为 1
        errors.append(f"protocol_version={proto_ver} is not standard SOME/IP value 1")

    if not isinstance(length, int):
        errors.append("length field is missing or not an integer")
    else:
        if length < 8:  #  # 规则1：SOMEIP头部固定16字节？这里标准定义：len字段代表【负载长度】，最小为8
            errors.append(f"length={length} is smaller than SOME/IP minimum 8")
        if 8 + length > payload_len:    # 规则2：16字节头 + len负载 不能超过传输层总负载，否则报文截断、数据残缺
            errors.append(
                f"length={length} implies total size {8 + length}, but transport payload is only {payload_len} bytes"
            )
    # 消息类型是否在合法集合
    if msg_type not in VALID_MESSAGE_TYPES:
        errors.append(f"message_type=0x{msg_type:02X} is not a known SOME/IP type")

    if errors:
        logger.debug("SOME/IP validation: %d issue(s) — %s", len(errors), "; ".join(errors))

    return errors

# 把从 PCAP 报文解析出来的原始数字字段，格式化组装成标准 SOME/IP 头部结构化字典 HeaderDict
# fields：原始解析字段字典
# 返回 HeaderDict：规范化后的 SOME/IP 头部结构体
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
    # TCP 分段扩展 TP 字段处理
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

# 接收单条 SOME/IP 报文的全部原始解析数据，组装成标准化、完整的单报文结构化字典 MessageDict
def build_message_dict(
    index: int,               # 当前SOME/IP报文的逻辑序号（自增计数，多条报文区分）
    frame_index: int,         # PCAP帧原始编号（wireshark里的帧序号）
    transport: TransportName, # 传输层枚举："UDP" / "TCP"
    pkt,                      # scapy完整数据包对象（包含IP/TCP/UDP层）
    fields: dict[str, Any],   # SOME/IP头部原始数字字段，传给 build_header_dict
    message_bytes: bytes,     # 完整SOME/IP报文二进制字节流（头部16字节 + payload）
) -> MessageDict:
    transport_layer = pkt[UDP] if transport == "UDP" else pkt[TCP]
    return {
        # 1. 报文索引信息
        "index": index,
        "frame_index": frame_index,
        "transport": transport,
        # 2. 解包注入 源IP/目的IP/源端口/目的端口 键值对
        **get_layer_endpoints(pkt, transport_layer),
        "header": build_header_dict(fields),
        "payload_hex": message_bytes[16:].hex(),       # 跳过前16字节标准头，载荷转十六进制字符串
        "payload_length": len(message_bytes) - 16,     # 载荷字节长度 = 总长度 - 16字节头部
        "raw_header_hex": message_bytes[:16].hex(),    # 前16字节标准SOME/IP头原始十六进制
    }

# 生成异常报文的标准化错误结构体 ErrorDict
def build_error_dict(
    frame_index: int,               # PCAP 原始帧编号，对应 Wireshark 帧号，快速定位异常包
    transport: TransportName,      # 传输层类型："UDP" / "TCP"
    pkt,                           # Scapy 完整数据包对象（含IP/TCP/UDP层）
    error_type: str,               # 错误分类标识（自定义字符串，如 "invalid_someip_header"、"tcp_reassemble_fail"、"payload_too_short"）
    reason: str | list[str],       # 错误详细描述，支持单条文本或多条错误列表
    raw_bytes: bytes | None = None,# 可选：捕获到的原始 SOME/IP 二进制字节流；解析完全失败时传 None
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