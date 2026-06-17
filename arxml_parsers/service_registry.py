"""
SOME/IP 服务注册表。
根据 ArxmlParser 提取的部署映射和接口信息，构建 O(1) 查找表。
作用：SOME/IP报文收发时，通过网络ID快速匹配对应的数据类型路径
"""
from __future__ import annotations
from dataclasses import dataclass, field
# 导入Parser产出的原始接口、部署、方法、事件数据类
from arxml_parser import (
    RawServiceDeployment,
    RawServiceEvent,
    RawServiceInterface,
    RawServiceMethod,
)


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
        # 第一步：缓存所有服务接口，兼容两种路径格式（原生路径 / 带/Package前缀路径）
        self._interface_index = {}
        for iface in interfaces:
            # 存入标准完整路径
            self._interface_index[iface.path] = iface
            # 兼容部分厂商ARXML引用时自动拼接 /Package 前缀的场景
            self._interface_index[f"/Package{iface.path}"] = iface

        # 第二步：遍历每一个服务的SOME/IP部署配置
        for dep in deployments:
            # 过滤无效服务ID（ID=0代表未分配网络ID，跳过）
            if not dep.service_id:
                continue
            # 根据部署里的接口引用路径，找到对应的逻辑服务接口定义
            iface = self._find_interface(dep.interface_ref)
            # 找不到对应接口，跳过本条部署
            if iface is None:
                continue

            # ========== 处理RPC方法，填充_method_map ==========
            for md in dep.methods:
                # md.method_ref 是完整路径，截取最后一段短名匹配接口内方法
                method_short_name = _last_segment(md.method_ref)
                # 从接口字典按方法名取出方法定义
                method = iface.methods.get(method_short_name)
                if method is None:
                    continue
                # 遍历该方法所有参数（IN/OUT/INOUT）
                for arg in method.arguments:
                    # 将参数方向IN/OUT/INOUT 转换为SOME/IP报文类型 request/response
                    msg_type = _direction_to_msg_type(arg.direction)
                    # 拼接唯一索引key：服务ID + 方法ID + 报文方向
                    map_key = (dep.service_id, md.method_id, msg_type)
                    # 存入映射：网络ID组合 → 参数数据类型路径
                    self._method_map[map_key] = arg.type_ref

            # ========== 处理广播事件，填充_event_map ==========
            for ed in dep.events:
                # 截取事件短名，匹配接口内事件
                event_short_name = _last_segment(ed.event_ref)
                evt = iface.events.get(event_short_name)
                # 事件存在且绑定了数据类型才存入映射
                if evt is not None and evt.type_ref:
                    event_key = (dep.service_id, ed.event_id)
                    self._event_map[event_key] = evt.type_ref

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
