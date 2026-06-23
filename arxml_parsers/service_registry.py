"""
SOME/IP 服务注册表。
根据 ArxmlParser 提取的部署映射和接口信息，构建 O(1) 查找表。
作用：SOME/IP报文收发时，通过网络ID快速匹配对应的数据类型路径
"""
from __future__ import annotations
from dataclasses import dataclass, field
# 导入Parser产出的原始接口、部署、方法、事件数据类
from .arxml_parser import (
    RawServiceDeployment,
    RawServiceEvent,
    RawServiceInterface,
    RawServiceMethod,
)
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ServiceRegistry:
    """
    SOME/IP 全局注册表，维护三层映射关系：
    1. (service_id, method_id, msg_type) → 数据类型路径（RPC请求/响应）
    2. (service_id, event_id) → 数据类型路径（广播事件）
    3. 接口完整路径 → RawServiceInterface 服务接口对象缓存
    """
    # RPC方法索引：key=(服务ID, 方法ID, request/response)，value=类型完整AR路径
    _method_map: dict[tuple[int, int, str], str] = field(default_factory=dict)
    # 广播事件索引：key=(服务ID, 事件ID)，value=事件承载数据的AR路径
    _event_map: dict[tuple[int, int], str] = field(default_factory=dict)
    # 接口缓存：AR完整路径 → 原始服务接口对象，用于通过部署ref反向查找接口定义
    _interface_index: dict[str, RawServiceInterface] = field(default_factory=dict)
    # 名称映射（供前端展示）
    _svc_name_map: dict[int, str] = field(default_factory=dict)
    _evt_name_map: dict[tuple[int, int], str] = field(default_factory=dict)
    _method_name_map: dict[tuple[int, int], str] = field(default_factory=dict)
    _eg_name_map: dict[tuple[int, int], str] = field(default_factory=dict)

    def build(
        self,
        deployments: list[RawServiceDeployment],
        interfaces: list[RawServiceInterface],
    ) -> None:
        """
        构建整张注册表，入口函数
        :param deployments: Parser输出的所有SOME/IP部署ID配置
        :param interfaces: Parser输出的所有服务接口逻辑定义
        """
        logger.info("Building registry: %d deployments, %d interfaces",
                    len(deployments), len(interfaces))

        # 第一步：缓存所有服务接口，兼容两种路径格式（原生路径 / 带/Package前缀路径）
        self._interface_index = {}
        for iface in interfaces:
            self._interface_index[iface.path] = iface
            self._interface_index[f"/Package{iface.path}"] = iface

        skipped_zero = 0
        skipped_no_iface = 0

        # 第二步：遍历每一个服务的SOME/IP部署配置
        for dep in deployments:
            if not dep.service_id:
                skipped_zero += 1
                continue
            iface = self._find_interface(dep.interface_ref)
            if iface is None:
                skipped_no_iface += 1
                logger.debug("Deployment interface not found: %s", dep.interface_ref)
                continue

            # ---- 记录 Service 名称 ----
            svc_name = _last_segment(dep.interface_ref)
            self._svc_name_map[dep.service_id] = svc_name

            # ---- 记录 EventGroup 名称 ----
            for eg in dep.event_groups:
                self._eg_name_map[(dep.service_id, eg.event_group_id)] = eg.name

            # ========== 处理RPC方法，填充_method_map ==========
            for md in dep.methods:
                method_short_name = _last_segment(md.method_ref)
                method = iface.methods.get(method_short_name)
                if method is None:
                    continue
                # 记录方法名称
                self._method_name_map[(dep.service_id, md.method_id)] = method_short_name
                for arg in method.arguments:
                    msg_type = _direction_to_msg_type(arg.direction)
                    map_key = (dep.service_id, md.method_id, msg_type)
                    self._method_map[map_key] = arg.type_ref

            # ========== 处理广播事件，填充_event_map ==========
            for ed in dep.events:
                event_short_name = _last_segment(ed.event_ref)
                evt = iface.events.get(event_short_name)
                if evt is not None and evt.type_ref:
                    event_key = (dep.service_id, ed.event_id)
                    self._event_map[event_key] = evt.type_ref
                # 记录事件名称
                self._evt_name_map[(dep.service_id, ed.event_id)] = event_short_name

        if skipped_zero:
            logger.debug("Skipped %d deployments with service_id=0", skipped_zero)
        if skipped_no_iface:
            logger.debug("Skipped %d deployments with missing interface", skipped_no_iface)
        logger.info("Registry built: %d methods, %d events",
                    len(self._method_map), len(self._event_map))

    # ==================== 对外查询API ====================
    def lookup_method(self, service_id: int, method_id: int, msg_type: str) -> str | None:
        """
        根据RPC三元组查询对应数据类型路径
        :param service_id: SOME/IP服务ID
        :param method_id: SOME/IP方法ID
        :param msg_type: "request" / "response"
        :return: 类型完整AR路径，无匹配返回None
        """
        return self._method_map.get((service_id, method_id, msg_type))

    def lookup_event(self, service_id: int, event_id: int) -> str | None:
        """
        根据服务ID+事件ID查询广播事件的数据类型路径
        """
        return self._event_map.get((service_id, event_id))

    def lookup_service_name(self, service_id: int) -> str | None:
        """根据 Service ID 查询服务名称。"""
        return self._svc_name_map.get(service_id)

    def lookup_event_name(self, service_id: int, event_id: int) -> str | None:
        """根据 Service ID + Event ID 查询事件名称。"""
        return self._evt_name_map.get((service_id, event_id))

    def lookup_method_name(self, service_id: int, method_id: int) -> str | None:
        """根据 Service ID + Method ID 查询方法名称。"""
        return self._method_name_map.get((service_id, method_id))

    def lookup_eventgroup_name(self, service_id: int, eg_id: int) -> str | None:
        """根据 Service ID + EventGroup ID 查询 EventGroup 名称。"""
        return self._eg_name_map.get((service_id, eg_id))

    @property
    def method_count(self) -> int:
        """统计注册的RPC报文总数"""
        return len(self._method_map)

    @property
    def event_count(self) -> int:
        """统计注册的广播事件总数"""
        return len(self._event_map)

    # ==================== 内部工具函数 ====================
    def _find_interface(self, ref: str) -> RawServiceInterface | None:
        """
        根据接口引用路径查找缓存的服务接口，兼容两种路径格式
        :param ref: 部署中记录的INTERFACE-REF路径字符串
        """
        # 优先直接精确匹配
        if ref in self._interface_index:
            return self._interface_index[ref]
        # 兼容两种格式互转：带/Package  <-> 不带/Package
        if ref.startswith("/Package"):
            alt_ref = ref[8:]
        else:
            alt_ref = f"/Package{ref}"
        return self._interface_index.get(alt_ref)


# 全局工具函数
def _last_segment(ref: str) -> str:
    """
    截取AR完整路径最后一段短名称
    例：/Data/Interface/ADCC_RtMM → ADCC_RtMM
    """
    clean_ref = ref.rstrip("/")
    return clean_ref.rsplit("/", 1)[-1]


def _direction_to_msg_type(direction: str) -> str:
    """
    AUTOSAR参数方向 → SOME/IP报文类型映射
    规则：
    OUT 参数 = 服务返回 response
    IN / INOUT = 客户端请求 request
    """
    d = direction.upper().strip()
    if d == "OUT":
        return "response"
    if d == "INOUT":
        # SOME/IP协议无原生INOUT，统一归为请求侧
        return "request"
    # IN / 未知方向默认request
    return "request"
