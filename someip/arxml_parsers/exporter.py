"""
ARXML 编译结果导出器。

将 ArxmlParser + TypeFactory + ServiceRegistry 的中间产物
序列化为可读的 JSON 报告，用于调试、存档或 Web 前端消费。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger(__name__)


def export_arxml_report(
    output_path: str | Path,
    *,
    raw_base_types: list[Any],
    raw_types: list[Any],
    raw_interfaces: list[Any],
    raw_deployments: list[Any],
    type_pool: dict[str, Any],
    registry: Any,
) -> None:
    """将完整 ARXML 编译结果写入单个 JSON 文件。

    Parameters
    ----------
    output_path: 输出文件路径。
    raw_base_types: ArxmlParser.raw_base_types。
    raw_types: ArxmlParser.raw_types。
    raw_interfaces: ArxmlParser.raw_interfaces。
    raw_deployments: ArxmlParser.raw_deployments。
    type_pool: TypeFactory.build_all() 返回的 dict。
    registry: ServiceRegistry 实例。
    """
    report = {
        "base_types": [
            {"name": bt.name, "path": bt.path, "bit_size": bt.bit_size,
             "byte_order": bt.byte_order, "encoding": bt.encoding}
            for bt in raw_base_types
        ],
        "types": [
            {"name": t.name, "path": t.path, "category": t.category,
             "type_ref": t.type_ref, "array_size": t.array_size,
             "sub_elements": [{"name": s.name, "type_ref": s.type_ref}
                              for s in t.sub_elements]}
            for t in raw_types
        ],
        "interfaces": [
            {"name": i.name, "path": i.path,
             "methods": {
                 n: [{"name": a.name, "type_ref": a.type_ref,
                      "direction": a.direction} for a in m.arguments]
                 for n, m in i.methods.items()
             },
             "events": {n: e.type_ref for n, e in i.events.items()}}
            for i in raw_interfaces
        ],
        "deployments": [
            {"service_id": d.service_id, "interface_ref": d.interface_ref,
             "method_ids": [m.method_id for m in d.methods],
             "event_ids": [e.event_id for e in d.events]}
            for d in raw_deployments
        ],
        "built_types": {
            path: {"kind": type(dt).__name__, "name": dt.name,
                   "byte_size": dt.byte_size}
            for path, dt in sorted(type_pool.items())
        },
        "registry": {
            "method_map": {str(k): v for k, v in registry._method_map.items()},
            "event_map": {str(k): v for k, v in registry._event_map.items()},
        },
    }
    path = Path(output_path)
    with path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info("ARXML report written: %s (%d bytes)", path, path.stat().st_size)
