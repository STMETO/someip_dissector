"""信号字段路径收集与取值测试。"""
from __future__ import annotations

import unittest

from someip.analysis.signal_utils import collect_leaf_paths, get_field_value


class SignalUtilsTests(unittest.TestCase):
    """覆盖普通结构体及 ARXML 数组根节点的路径解析。"""

    def test_reads_regular_nested_field(self):
        parsed = _container("Root", [
            _container("status", [_leaf("speed", 42)]),
        ])

        self.assertEqual(collect_leaf_paths(parsed), ["status.speed"])
        self.assertEqual(get_field_value(parsed, ["status", "speed"]), 42)

    def test_reads_field_when_array_root_and_element_share_base_name(self):
        type_path = "/DataTypes/ImplementationDataTypes/ADAS_arr_DynamicObjects_2"
        parsed = _container(type_path, [
            _container(f"{type_path}[0]", [_leaf("objectId", 38989)]),
            _container(f"{type_path}[1]", [_leaf("objectId", 39123)]),
        ])

        expected_path = f"{type_path}.objectId"
        self.assertEqual(collect_leaf_paths(parsed), [expected_path])
        self.assertEqual(
            get_field_value(parsed, expected_path.split(".")),
            38989,
        )


def _container(name: str, children: list[dict]) -> dict:
    """构造测试用容器节点。"""
    return {"name": name, "kind": "container", "children": children}


def _leaf(name: str, value: int | float) -> dict:
    """构造测试用数值叶子节点。"""
    return {"name": name, "kind": "leaf", "value": value}


if __name__ == "__main__":
    unittest.main()
