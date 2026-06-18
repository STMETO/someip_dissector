"""解析管道：串联 PCAP 解析 → ARXML 编译 → 反序列化。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pcap_parsers.parser import SomeIpPcapParser
from pcap_parsers.strategies import TcpSomeIpStrategy, UdpSomeIpStrategy
from arxml_parsers import ArxmlParser, TypeFactory, ServiceRegistry
from deserialization import DeserializationEngine
from utils.logger import get_logger

logger = get_logger(__name__)


def run_analysis_pipeline(
    pcap_path: Path,
    arxml_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """执行全链路解析，返回 (messages, type_pool_info, registry_info)。

    Returns
    -------
    messages : list[dict]
        每条消息包含原始字段 + 反序列化树 "tree"。
    type_pool_info : dict
        {path: {"kind": ..., "name": ..., "byte_size": ...}}。
    registry_info : dict
        {"method_map": {...}, "event_map": {...}}。
    """
    # ---- 1. PCAP ----
    logger.info("Web: parsing pcap %s", pcap_path)
    parser = SomeIpPcapParser([UdpSomeIpStrategy(), TcpSomeIpStrategy()])
    pcap_result = parser.parse(pcap_path, Path("/dev/null"))
    messages = pcap_result["messages"]
    logger.info("Web: pcap → %d messages", len(messages))

    # ---- 2. ARXML ----
    logger.info("Web: parsing arxml %s", arxml_path)
    xml_parser = ArxmlParser(arxml_path)
    xml_parser.parse()
    type_pool = TypeFactory().build_all(xml_parser.raw_base_types, xml_parser.raw_types)
    registry = ServiceRegistry()
    registry.build(xml_parser.raw_deployments, xml_parser.raw_interfaces)
    logger.info("Web: arxml → %d types, %d methods, %d events",
                len(type_pool), registry.method_count, registry.event_count)

    # ---- 3. Deserialize ----
    engine = DeserializationEngine(type_pool, registry)
    for msg in messages:
        tree = engine.deserialize_message(msg)
        if tree is not None:
            msg["tree"] = tree.to_dict()
        else:
            msg["tree"] = None

    # 内存中保留的类型信息
    type_pool_info = {
        path: {"kind": type(dt).__name__, "name": dt.name, "byte_size": dt.byte_size}
        for path, dt in sorted(type_pool.items())
    }
    registry_info = {
        "method_map": {str(k): v for k, v in registry._method_map.items()},
        "event_map": {str(k): v for k, v in registry._event_map.items()},
    }

    return messages, type_pool_info, registry_info
