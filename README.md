# SOME/IP Dissector

基于 Python 的 SOME/IP（Scalable service-Oriented MiddlewarE over IP）协议解析工具链。
覆盖从 PCAP 报文捕获、SOME/IP 头部解析、SOME/IP-SD 服务发现、ARXML 服务定义编译，
到二进制 Payload 反序列化的全链路。

---

## 环境准备

### 安装依赖

```bash
pip install scapy lxml typing_extensions
pip install fastapi uvicorn python-multipart aiofiles websockets
```

| 依赖 | 用途 |
|------|------|
| `scapy` | PCAP 读取、SOME/IP 与 SOME/IP-SD 协议栈 |
| `lxml` | ARXML 文件解析 |
| `typing_extensions` | Python < 3.11 的 `NotRequired` 兼容 |

### 进入容器（可选）

```bash
docker exec -it someip_dissector /bin/bash
```

---

## 项目架构

> ✅ 已实现 &nbsp;&nbsp; ⬜ 规划中

```
someip_dissector/
│
├── pcap_parsers/                       ✅
│   ├── __init__.py                     # 包导出
│   ├── common.py                       # TypedDict 类型、SOME/IP 校验、SOME/IP-SD 常量
│   ├── strategies.py                   # 策略模式：UDP 单包解析 / TCP 流重组
│   └── parser.py                       # 调度器，遍历 pcap 帧 → 分发策略 → 写 JSON
│
├── datatypes/                          ✅
│   ├── __init__.py                     # 包导出
│   └── types.py                        # DataType 类族（BaseType / BoolType / StructureType / ArrayType / StringType）
│
├── arxml_parsers/                      ✅
│   ├── __init__.py                     # 包导出
│   ├── arxml_parser.py                 # lxml 提取 SW-BASE-TYPE、STD-CPP 类型、接口、部署
│   ├── type_factory.py                 # Factory + Builder 模式构建 DataType 对象池
│   └── service_registry.py             # Registry 模式：(srv_id, method_id, msg_type) → type_path
│
├── deserialization/                    ✅
│   ├── engine.py                       # 反序列化引擎
│   └── field_node.py                   # 字段树节点
│
├── output/                             ✅
│
├── web/                                ✅
│   ├── app.py                          # FastAPI 入口（uvicorn 启动）
│   ├── handlers/                       # 上传、解析管道业务逻辑
│   ├── views/                          # 页面 HTML 片段
│   ├── utils/                          # 会话管理、导出
│   └── static/                         # CSS / JS 静态资源
│
├── utils/                              ✅
│   ├── __init__.py
│   └── logger.py                       # 统一日志：控制台 + RotatingFileHandler
│
├── test/                               ✅
│   ├── test_pcap_parsers/              # PCAP 解析单元测试
│   ├── test_arxml_parsers/             # ARXML 解析单元测试
│   └── test_deserialization/           # 反序列化单元测试
│
├── Tools/                              ✅
│   └── generate_sample_pcap.py         # 纯 Python 生成测试用 pcap
│
└── README.md
```

---

## 模块详解

### pcap_parsers — SOME/IP 报文解析

**阅读顺序**：`common.py` → `strategies.py` → `parser.py`

```
sample.pcap
  → SomeIpPcapParser.parse()
    → PcapReader 逐帧遍历
    → UdpSomeIpStrategy / TcpSomeIpStrategy 提取 SOME/IP 报文
    → srv_id == 0xFFFF 时自动内联 SD 解析
    → 输出 MessageDict[] + ErrorDict[] → sample.json
```


### arxml_parsers — 服务定义编译

**阅读顺序**：`datatypes/types.py` → `arxml_parser.py` → `type_factory.py` → `service_registry.py`

```
sample.arxml
  → ArxmlParser.parse()
    ├─ raw_base_types[]           (SW-BASE-TYPE → bit_size, byte_order)
    ├─ raw_types[]                (STD-CPP-IMPLEMENTATION-DATA-TYPE)
    ├─ raw_interfaces[]           (SERVICE-INTERFACE → methods, events)
    └─ raw_deployments[]          (SOMEIP-SERVICE-INTERFACE-DEPLOYMENT)
      │
      ├─→ TypeFactory.build_all()
      │     Pass 1: Builder 策略创建骨架 + 收集 TYPE_REFERENCE 别名
      │     Pass 2: _resolve_chain 穿透引用链解析字段/元素类型
      │     Pass 3: 替换占位符 → {path: DataType}
      │
      └─→ ServiceRegistry.build()
            (srv_id, method_id, request/response) → type_path   O(1)
            (srv_id, event_id)                 → type_path       O(1)
```


### utils/logger — 统一日志

```python
from utils.logger import setup_logging, get_logger

setup_logging(level="INFO")               # 仅控制台
setup_logging(level="DEBUG", log_dir="./logs")  # + 文件轮转

logger = get_logger(__name__)
```

---

## 解析链路

```
PCAP 原始报文
  → 解析传输层 (TCP/UDP)
    → 提取 SOME/IP 标准头部（Service ID / Method ID / Message Type）
      → srv_id == 0xFFFF → 内联 SOME/IP-SD 解析（Entry / Option）
      → 检索 ARXML 编译的 ServiceRegistry
        → 定位入参 / 出参 / 事件数据类型路径
          → TypeFactory 获取 DataType 对象（字段布局 + 偏移 + 字节序）
            → 二进制 Payload 递归反序列化
              → 结构化输出（JSON / Console / HTML）
```

---

## 运行测试

```bash
# PCAP 解析
python test/test_pcap_parsers/test_pcap_parsers.py

# ARXML 解析
python test/test_arxml_parsers/test_arxml_parsers.py

# 反序列化
python test/test_deserialization/test_deserialization.py
```

---

## 运行 Web 界面

技术栈：Vue 3 + Element Plus（前端）/ FastAPI（后端），前后端分离。

```bash
# 1. 安装后端依赖
pip install fastapi uvicorn python-multipart aiofiles

# 2. 启动后端（端口 8000）
python web/backend/app.py

# 3. 安装前端依赖（首次）
cd web/frontend && npm install

# 4. 启动前端开发服务器（端口 3000，自动代理到 8000）
npm run dev
```

浏览器打开 `http://localhost:3000`，上传 pcap + arxml 开始分析。

| 地址 | 用途 |
|------|------|
| `http://localhost:3000` | 前端页面 |
| `http://localhost:8000/docs` | 后端 API 文档 (Swagger) |