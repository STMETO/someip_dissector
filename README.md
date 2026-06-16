# SOME/IP Dissector

基于 Python 的 SOME/IP（Scalable service-Oriented MiddlewarE over IP）协议解析工具链，支持从 PCAP 网络抓包到 ARXML 服务定义的全链路反序列化与结构化输出。

---

## 环境准备

### 进入容器

```bash
docker exec -it someip_dissector /bin/bash
```

### 安装依赖

```bash
pip install scapy typing_extensions
```

---

## 项目架构

#### 目前仅实现部分，大部分是预期，后期同步修改

```
someip_dissector/
├── pcap_parsers/
│   ├── __init__.py                 # 包导出
│   ├── main.py                     # 入口：pcap → JSON
│   ├── parser.py                   # SOME/IP 解析调度器（策略模式）
│   ├── common.py                   # 类型定义、常量和工具函数
│   └── strategies.py               # UDP/TCP 传输层解析策略（含 TCP 流重组）
├── arxml_parsers/
│   ├── arxml_parser.py             # 解析 ARXML，提取服务接口和数据类型
│   ├── type_factory.py             # 根据解析结果创建 DataType 对象
│   └── service_registry.py         # 服务查找表
├── datatypes/
│   ├── base.py                     # DataType 抽象基类
│   ├── primitives.py               # 基础类型：UInt8, UInt16, Int32...
│   ├── struct.py                   # StructType 复合类型
│   ├── array.py                    # ArrayType 与长度策略
│   ├── string.py                   # 字符串类型
│   └── parse_context.py            # 解析上下文
├── deserialization/
│   ├── engine.py                   # 反序列化引擎，协调各组件
│   └── field_node.py               # 字段树节点
├── output/
│   ├── text_visitor.py             # 控制台树形输出
│   ├── json_visitor.py             # JSON 序列化
│   └── html_visitor.py             # HTML 可视化（可嵌入 Web）
├── web/
│   ├── app.py                      # Web 入口（Flask/FastAPI）
│   ├── templates/
│   └── static/
├── utils/
│   └── logger.py                   # 统一日志
├── config.py                       # 全局配置
└── main.py                         # CLI 入口，整合完整管道
```

---

## 解析链路

```
PCAP 原始报文
  → 解析传输层 (TCP/UDP)
    → 提取 SOME/IP 标准头部
      → 提取五元组 + 报文类型
        → 检索 ARXML 构建的全局注册表
          → 定位入参 / 出参 / 事件数据 / 字段
            → 获取数据类型定义
              → 二进制 Payload 递归反序列化
                → 结构化输出
```