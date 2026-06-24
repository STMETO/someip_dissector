# SOME/IP Dissector

基于 Python 的 SOME/IP（Scalable service-Oriented MiddlewarE over IP）协议解析工具链。
覆盖 PCAP 报文捕获 → SOME/IP 头部解析 → SOME/IP-SD 服务发现 → TP 分片重组
→ ARXML 服务定义编译 → 二进制 Payload 反序列化 → Web 可视化的**全链路分析**。

---

## 环境准备

### 1. Python 依赖

```bash
pip install scapy lxml typing_extensions
pip install fastapi uvicorn python-multipart aiofiles
```

| 依赖 | 用途 |
|------|------|
| `scapy` | PCAP 读取、SOME/IP/SOME/IP-SD 协议栈 |
| `lxml` | ARXML 文件解析（XPath + 命名空间） |
| `fastapi` / `uvicorn` | Web 后端 API 服务 |
| `python-multipart` | 文件上传表单解析 |
| `aiofiles` | 异步文件 I/O |
| `typing_extensions` | Python < 3.11 的 `NotRequired` 兼容 |

### 2. 前端环境（Node.js + npm）

前端基于 **Vue 3 + Vite + Element Plus + ECharts**，需要 Node.js ≥ 18。

```bash
# 检查 Node.js 版本
node --version   # 需要 ≥ 18

# 安装前端依赖（仅首次）
cd web/frontend && npm install

# 构建前端
npm run build
```

| 前端依赖 | 用途 |
|----------|------|
| `vue` (^3.3) | 渐进式 UI 框架（Composition API + SFC） |
| `element-plus` (^2.3) | UI 组件库 |
| `axios` (^1.6) | HTTP 客户端 |
| `echarts` | 信号时序多曲线图表 |
| `vite` (^4.0) | 构建工具 (HMR + Rollup) |
| `@vitejs/plugin-vue` (^4.0) | Vite Vue 3 SFC 编译 |

> **提示**：容器环境如需手动安装 Node.js：
> ```bash
> wget https://nodejs.org/dist/v20.11.0/node-v20.11.0-linux-x64.tar.xz
> tar -xf node-v20.11.0-linux-x64.tar.xz
> export PATH=$PWD/node-v20.11.0-linux-x64/bin:$PATH
> ```
> `web/start.py` 会在首次启动时自动检测并构建前端。

---

## 项目架构

```
someip_dissector/
│
├── pcap_parsers/                       # SOME/IP 报文解析 + TP 分片重组
│   ├── common.py                       # TypedDict 类型、校验、msg_type 统一映射
│   ├── strategies.py                   # 策略模式：UDP 单包 / TCP 流重组
│   ├── parser.py                       # 调度器 + TP 重组 + SD 解析
│   └── message_view.py                 # 原始数据展示树：msg dict → FieldNode
│
├── datatypes/                          # 共享数据类型体系
│   └── types.py                        # DataType 类族（BaseType/BoolType/
│                                       #   StringType/StructureType/ArrayType）
│
├── arxml_parsers/                      # ARXML 服务定义编译
│   ├── arxml_parser.py                 # lxml 提取全部 ARXML 元素
│   ├── type_factory.py                 # Factory + Builder → DataType 对象池
│   ├── service_registry.py             # Registry：O(1) 查表 + ID→名称映射
│   └── exporter.py                     # 中间产物 JSON 导出
│
├── deserialization/                    # 二进制 Payload 反序列化
│   ├── engine.py                       # 引擎：ID 查表 → 类型匹配 → 递归解析
│   └── field_node.py                   # 解析树节点（leaf / container）
│
├── analysis/                           # 信号分析模块
│   ├── signal_utils.py                 # 字段提取 + 跳变检测
│   └── sd_diagnostic.py                # SD 订阅诊断（Offer→Subscribe→Notify 链路）
│
├── utils/                              # 工具模块
│   └── logger.py                       # 统一日志：控制台 + RotatingFileHandler
│
├── web/                                # Web 界面（FastAPI + Vue 3）
│   ├── start.py                        # 一键启动（自动构建前端 + uvicorn）
│   ├── backend/
│   │   ├── app.py                      # FastAPI 入口 + API 路由 + 静态文件
│   │   └── handlers/
│   │       ├── analysis.py             # 管道编排 + 会话管理 + API 格式化
│   │       ├── upload.py               # 异步文件上传 + 校验
│   │       ├── signal_timing.py        # 信号时序 API
│   │       └── sd_diagnostic.py        # SD 诊断 API
│   └── frontend/
│       ├── src/
│       │   ├── App.vue                 # 单页布局 + Tab 切换
│       │   ├── api/index.js            # Axios API 封装
│       │   └── components/
│       │       ├── UploadBar.vue       # 拖拽上传
│       │       ├── MessageTable.vue    # 消息列表（搜索/列宽拖动）
│       │       ├── ParseTree.vue       # 双视图递归树
│       │       ├── SignalSelector.vue  # 三级级联 + 多选字段
│       │       ├── SignalChart.vue     # ECharts 多曲线时序图
│       │       ├── SignalTiming.vue    # 信号时序页
│       │       └── SubscriptionReport.vue  # 订阅诊断报告
│       ├── package.json
│       └── vite.config.js
│
├── test/                               # 测试 & 调试入口
│   ├── main.py                         # 命令行调试入口（argparse）
│   ├── test_pcap_parsers/              # PCAP 解析测试
│   ├── test_arxml_parsers/             # ARXML 解析测试
│   └── test_deserialization/           # 全链路反序列化测试
│
├── Tools/
│   └── generate_sample_pcap.py         # 测试用 pcap 生成器
│
├── run.py                              # 跨平台启动器（唯一入口）
└── README.md
```

---

## 阅读顺序

### pcap_parsers
`common.py` → `strategies.py` → `parser.py` → `message_view.py`

### arxml_parsers
`arxml_parser.py` → `type_factory.py` → `service_registry.py`

### deserialization
`field_node.py` → `engine.py`

### analysis
`signal_utils.py` → `sd_diagnostic.py`

### web
`handlers/analysis.py` → `app.py` → 前端 `App.vue` → 各组件

---

## 解析链路

```
PCAP 原始报文
  → 传输层解析 (UDP/TCP)
    → 提取 SOME/IP 头部（Service ID / Method ID / Message Type）
      → msg_type & 0x20 → TP 分片自动重组（offset 排序 + payload 拼接）
      → srv_id == 0xFFFF → 内联 SOME/IP-SD 解析（Entry / Option）
      → 检索 ServiceRegistry（含 ID→名称映射）
        → TypeFactory 获取 DataType（字段布局 + 偏移 + 字节序）
          → 二进制 Payload 流式递归反序列化
            → 每条消息输出 raw_view + parsed 双树
```

---

## 快速开始

### 统一入口

```bash
python run.py                     # 查看用法
python run.py web                 # 启动 Web 界面
python run.py debug [选项]        # 命令行批处理
```

### Web 界面

```bash
python run.py web
```

浏览器打开 **http://localhost:8000**：

| Tab | 功能 |
|-----|------|
| 📋 报文解析 | 消息列表（搜索/列宽拖动）+ 双视图树（Raw PCAP / Deserialized） |
| 📈 信号时序 | 多字段同时绘制曲线 + 跳变点标记，缩放/悬停/图例切换 |
| 🔍 订阅诊断 | SD 订阅链路分析（Offer→Subscribe→Notification），异常红色高亮 |

| 地址 | 用途 |
|------|------|
| `http://localhost:8000` | Web 界面 |
| `http://localhost:8000/docs` | API 文档 (Swagger) |

### 命令行调试

```bash
python run.py debug                           # 默认参数
python run.py debug --pcap my.pcap --arxml my.arxml
python run.py debug --log-level INFO --output /tmp/out
python run.py debug --help                    # 查看所有选项
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--pcap` | `test/test_deserialization/sample.pcap` | PCAP 文件路径 |
| `--arxml` | `test/test_deserialization/sample.arxml` | ARXML 文件路径 |
| `--log-level` | `DEBUG` | 日志等级 |
| `--output` | `output/<时间戳>` | 结果输出目录 |
| `--log-dir` | `logs/<时间戳>` | 日志目录 |
| `--save-json` | `True` | 保存中间 JSON |

### 运行测试

```bash
python test/test_pcap_parsers/test_pcap_parsers.py
python test/test_arxml_parsers/test_arxml_parsers.py
python test/test_deserialization/test_deserialization.py

# 完整 pipeline（等同于 ./run.sh debug）
python test/main.py
```

---

## 设计模式

| 模式 | 位置 | 说明 |
|------|------|------|
| **策略模式** | `pcap_parsers/strategies.py` | UDP / TCP 传输层解析可插拔 |
| **工厂 + Builder** | `arxml_parsers/type_factory.py` | CATEGORY → Builder → DataType |
| **注册表** | `arxml_parsers/service_registry.py` | O(1) 查表 + ID → 名称映射 |
| **流式反序列化** | `deserialization/` | 返回 `(FieldNode, consumed_bytes)` |
| **递归组合** | `datatypes/types.py` | Struct/Array 嵌套 DataType |
| **数据视图分离** | `pcap_parsers/message_view.py` | 展示树与解析逻辑解耦 |
| **胶水层** | `web/backend/handlers/` | handler 仅编排，核心逻辑在 analysis/ |

---

## msg_type 兼容性

| 类型 | 值 | TP 版本 | 说明 |
|------|-----|---------|------|
| REQUEST | 0x00 | 0x20 | 请求 |
| REQUEST_NO_RETURN | 0x01 | 0x21 | 无返回请求 |
| NOTIFICATION | 0x02 | **0x22** | 通知/事件 |
| RESPONSE | 0x80 | 0xA0 | 响应 |
| ERROR | 0x81 | — | 错误响应 |

> TP 分片在 `parser.py` 的 `_reassemble_tp()` 中自动重组，对下游透明。
