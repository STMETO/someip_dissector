"""
SOME/IP 服务注册表。

根据 ArxmlParser 提取的部署映射和接口信息，构建 O(1) 查找表。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from arxml_parser import (
    RawServiceDeployment,
    RawServiceEvent,
    RawServiceInterface,
    RawServiceMethod,
)


@dataclass
class ServiceRegistry:
    """(service_id, method_id, msg_type) → type_path 快速查找。"""

    _method_map: dict[tuple[int, int, str], str] = field(default_factory=dict)
    _event_map: dict[tuple[int, int], str] = field(default_factory=dict)
    _interface_index: dict[str, RawServiceInterface] = field(default_factory=dict)

    def build(
        self,
        deployments: list[RawServiceDeployment],
        interfaces: list[RawServiceInterface],
    ) -> None:
        # 索引：支持多种路径变体
        self._interface_index = {}
        for iface in interfaces:
            self._interface_index[iface.path] = iface
            # 也支持带 /Package 前缀的引用
            self._interface_index[f"/Package{iface.path}"] = iface

        for dep in deployments:
            if not dep.service_id:  # service_id=0 无效
                continue
            iface = self._find_interface(dep.interface_ref)
            if iface is None:
                continue

            # 方法映射
            for md in dep.methods:
                method = iface.methods.get(_last_segment(md.method_ref))
                if method is None:
                    continue
                for arg in method.arguments:
                    msg_type = _direction_to_msg_type(arg.direction)
                    key = (dep.service_id, md.method_id, msg_type)
                    self._method_map[key] = arg.type_ref

            # 事件映射
            for ed in dep.events:
                evt = iface.events.get(_last_segment(ed.event_ref))
                if evt is not None and evt.type_ref:
                    self._event_map[(dep.service_id, ed.event_id)] = evt.type_ref

    # ---- 查询 ----

    def lookup_method(self, service_id: int, method_id: int, msg_type: str) -> str | None:
        return self._method_map.get((service_id, method_id, msg_type))

    def lookup_event(self, service_id: int, event_id: int) -> str | None:
        return self._event_map.get((service_id, event_id))

    @property
    def method_count(self) -> int:
        return len(self._method_map)

    @property
    def event_count(self) -> int:
        return len(self._event_map)

    # ---- 内部 ----

    def _find_interface(self, ref: str) -> RawServiceInterface | None:
        if ref in self._interface_index:
            return self._interface_index[ref]
        alt = f"/Package{ref}" if not ref.startswith("/Package") else ref[8:]
        return self._interface_index.get(alt)


def _last_segment(ref: str) -> str:
    return ref.rstrip("/").rsplit("/", 1)[-1]


def _direction_to_msg_type(direction: str) -> str:
    d = direction.upper().strip()
    if d in ("OUT",):
        return "response"
    if d in ("INOUT",):
        return "request"   # SOME/IP 没有真正的 INOUT，暂作 request
    return "request"       # IN 或未知
