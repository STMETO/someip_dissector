"""arxml_parsers 模块测试脚本。"""

import json
from pathlib import Path

from arxml_parser import ArxmlParser
from type_factory import TypeFactory
from service_registry import ServiceRegistry

BASE = Path(__file__).resolve().parent
ARXML_PATH = BASE / "sample.arxml"
OUTPUT_PATH = BASE / "test_output.json"

# ---- 1. 解析 ARXML ----
parser = ArxmlParser(ARXML_PATH)
parser.parse()

print(f"Data types: {len(parser.raw_types)}")
print(f"Interfaces: {len(parser.raw_interfaces)}")
print(f"Deployments: {len(parser.raw_deployments)}")

# ---- 2. 构建类型对象 ----
factory = TypeFactory()
types = factory.build_all(parser.raw_types)

print(f"Built {len(types)} DataType objects:")
for path, dt in sorted(types.items()):
    print(f"  {path} → {dt}")

# ---- 3. 构建注册表 ----
registry = ServiceRegistry()
registry.build(parser.raw_deployments, parser.raw_interfaces)

print(f"\nRegistry: {registry.method_count} methods, {registry.event_count} events")

# ---- 4. 输出 JSON ----
output = {
    "parser": {
        "type_count": len(parser.raw_types),
        "interface_count": len(parser.raw_interfaces),
        "deployment_count": len(parser.raw_deployments),
        "types": [
            {"name": t.name, "path": t.path, "category": t.category,
             "base_type_ref": t.base_type_ref,
             "sub_element_count": len(t.sub_elements)}
            for t in parser.raw_types
        ],
        "interfaces": [
            {"name": i.name, "path": i.path,
             "methods": {n: list(m.arguments.keys()) for n, m in i.methods.items()},
             "events": list(i.events.keys())}
            for i in parser.raw_interfaces
        ],
        "deployments": [
            {"service_id": d.service_id, "interface_ref": d.interface_ref,
             "method_ids": [m.method_id for m in d.methods],
             "event_ids": [e.event_id for e in d.events]}
            for d in parser.raw_deployments
        ],
    },
    "types": {
        path: {
            "kind": type(dt).__name__,
            "name": dt.name,
            "byte_size": dt.byte_size,
            "fields": [
                {"name": f.name, "type_ref": f.type_ref,
                 "offset": f.offset, "byte_size": f.byte_size,
                 "resolved": repr(f.resolved_type)}
                for f in dt.fields
            ] if hasattr(dt, "fields") else [],
        }
        for path, dt in sorted(types.items())
    },
    "registry": {
        "method_count": registry.method_count,
        "event_count": registry.event_count,
    },
}

with OUTPUT_PATH.open("w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\nOutput: {OUTPUT_PATH}")
print("Done.")
