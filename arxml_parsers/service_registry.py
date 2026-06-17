"""
SOME/IP 服务注册表。

根据 ArxmlParser 提取的部署映射和接口信息，构建 O(1) 查找表，
对外提供简洁的查询接口。

设计模式：**Registry** — 封装查找逻辑，外部无需关心内部数据结构。
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
class MethodKey:
    """方法查找键：(service_id, method_id, message_type)。"""

    service_id: int
    method_id: int
    message_type: str  # 'request' | 'response' | 'error'


@dataclass
class EventKey:
    """事件查找键：(service_id, event_id)。"""

    service_id: int
    event_id: int


@dataclass
class ServiceRegistry:
    """服务注册表。

    用法::

        registry = ServiceRegistry()
        registry.build(raw_deployments, raw_interfaces)
        type_path = registry.lookup_method(0x1234, 1, 'request')
    """

    # 内部存储
    _method_map: dict[tuple[int, int, str], str] = field(default_factory=dict)
    _event_map: dict[tuple[int, int], str] = field(default_factory=dict)
    _interface_index: dict[str, RawServiceInterface] = field(
        default_factory=dict
    )

    def build(
        self,
        deployments: list[RawServiceDeployment],
        interfaces: list[RawServiceInterface],
    ) -> None:
        """根据部署和接口数据构建全部映射表。"""
        # 索引接口：同时存储原始路径和短名称以提高命中率
        self._interface_index = {}
        for iface in interfaces:
            self._interface_index[iface.path] = iface
            self._interface_index[f"/Package{iface.path}"] = iface

        for dep in deployments:
            iface = self._find_interface(dep.interface_ref)
            if iface is None:
                continue

            # --- 方法映射 ---
            for md in dep.methods:
                method = self._resolve_method(iface, md.method_ref)
                if method is None:
                    continue
                for arg_name, type_ref in method.arguments.items():
                    msg_type = _arg_to_msg_type(arg_name)
                    key = (dep.service_id, md.method_id, msg_type)
                    self._method_map[key] = type_ref

            # --- 事件映射 ---
            for ed in dep.events:
                evt = self._resolve_event(iface, ed.event_ref)
                if evt is not None and evt.type_ref:
                    key = (dep.service_id, ed.event_id)
                    self._event_map[key] = evt.type_ref

    # ---- 查询接口 ----

    def lookup_method(
        self, service_id: int, method_id: int, message_type: str
    ) -> str | None:
        """查询 (service_id, method_id, message_type) 对应的类型路径。"""
        return self._method_map.get((service_id, method_id, message_type))

    def lookup_event(
        self, service_id: int, event_id: int
    ) -> str | None:
        """查询 (service_id, event_id) 对应的类型路径。"""
        return self._event_map.get((service_id, event_id))

    # ---- 辅助 ----

    def _find_interface(self, ref: str) -> RawServiceInterface | None:
        """通过引用路径查找接口（支持短名称 fallback）。"""
        if ref in self._interface_index:
            return self._interface_index[ref]
        # 尝试 /Package 变体
        alt = f"/Package{ref}" if not ref.startswith("/Package") else ref[8:]
        return self._interface_index.get(alt)

    @staticmethod
    def _resolve_method(
        iface: RawServiceInterface, method_ref: str
    ) -> RawServiceMethod | None:
        return iface.methods.get(_last_segment(method_ref))

    @staticmethod
    def _resolve_event(
        iface: RawServiceInterface, event_ref: str
    ) -> RawServiceEvent | None:
        return iface.events.get(_last_segment(event_ref))

    @property
    def method_count(self) -> int:
        return len(self._method_map)

    @property
    def event_count(self) -> int:
        return len(self._event_map)


def _last_segment(ref: str) -> str:
    """从路径 /A/B/C 中提取最后一段 C。"""
    return ref.rstrip("/").rsplit("/", 1)[-1]


def _arg_to_msg_type(arg_name: str) -> str:
    """根据参数名推断消息类型。"""
    lower = arg_name.lower()
    if "response" in lower or "reply" in lower or "result" in lower:
        return "response"
    if "error" in lower or "fault" in lower:
        return "error"
    return "request"
