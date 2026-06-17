"""Test script for arxml_parsers -- reads sample.arxml, outputs test_output.json."""

import json
from pathlib import Path

from arxml_parser import ArxmlParser
from type_factory import TypeFactory
from service_registry import ServiceRegistry

BASE = Path(__file__).resolve().parent
ARXML_PATH = BASE / "sample.arxml"
OUTPUT_PATH = BASE / "test_output.json"

# ---- 1. Parse ----
parser = ArxmlParser(ARXML_PATH)
parser.parse()
print(f"Base types:  {len(parser.raw_base_types)}")
print(f"Impl types:  {len(parser.raw_types)}")
print(f"Interfaces:  {len(parser.raw_interfaces)}")
print(f"Deployments: {len(parser.raw_deployments)}")

# ---- 2. Build types ----
factory = TypeFactory()
types = factory.build_all(parser.raw_base_types, parser.raw_types)
print(f"Built types: {len(types)}")

# ---- 3. Build registry ----
registry = ServiceRegistry()
registry.build(parser.raw_deployments, parser.raw_interfaces)
print(f"Registry: {registry.method_count} methods, {registry.event_count} events")

# ---- 4. Output ----
output = {
    "base_types": [
        {"name": bt.name, "path": bt.path, "bit_size": bt.bit_size,
         "byte_order": bt.byte_order, "encoding": bt.encoding}
        for bt in parser.raw_base_types
    ],
    "types": [
        {"name": t.name, "path": t.path, "category": t.category,
         "type_ref": t.type_ref, "array_size": t.array_size,
         "sub_elements": [{"name": s.name, "type_ref": s.type_ref} for s in t.sub_elements]}
        for t in parser.raw_types
    ],
    "interfaces": [
        {"name": i.name, "path": i.path,
         "methods": {
             n: [{"name": a.name, "type_ref": a.type_ref, "direction": a.direction}
                 for a in m.arguments]
             for n, m in i.methods.items()
         },
         "events": {n: e.type_ref for n, e in i.events.items()}}
        for i in parser.raw_interfaces
    ],
    "deployments": [
        {"service_id": d.service_id, "interface_ref": d.interface_ref,
         "method_ids": [m.method_id for m in d.methods],
         "event_ids": [e.event_id for e in d.events]}
        for d in parser.raw_deployments
    ],
    "built_types": {
        path: {"kind": type(dt).__name__, "name": dt.name, "byte_size": dt.byte_size}
        for path, dt in sorted(types.items())
    },
    "registry": {
        "method_map": {str(k): v for k, v in registry._method_map.items()},
        "event_map": {str(k): v for k, v in registry._event_map.items()},
    },
}

with OUTPUT_PATH.open("w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\nOutput: {OUTPUT_PATH}")
print("Done.")
