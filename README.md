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

前端基于 **Vue 3 + Vite + ECharts**，需要 Node.js ≥ 18。

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
| `axios` (^1.6) | HTTP 客户端 |
| `echarts` | 信号时序多曲线图表 |
| `marked` | 将模型回答解析为 GFM Markdown |
| `dompurify` | 清理 Markdown 生成的 HTML，阻止不安全标签和属性 |
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
│   └── message_view.py                 # 兼容包装：转发到 presentation.message_view
│
├── assistant/                          # AI 问答编排层（不依赖具体 Web 页面）
│   ├── __init__.py                     # 对外导出配置、问答和会话清理接口
│   ├── config.py                       # 模型地址、模型名称和进程内 API Key
│   ├── provider.py                     # OpenAI-compatible 请求客户端
│   ├── schemas.py                      # 配置和对话请求的 Pydantic 模型
│   ├── service.py                      # 对话上下文、系统提示词和 Tool Calling 循环
│   ├── tool_support.py                 # Tool 共用参数校验、会话读取和证据格式化
│   └── tools/                          # 一个文件实现一个只读查询 Tool
│       ├── __init__.py                 # Tool Schema 注册表和服务端调用白名单
│       ├── subscription_status.py      # Offer / Subscribe / Ack / Notification 总览
│       ├── find_service.py             # 按 ID 或 ARXML 名称查找服务
│       ├── offer_timeline.py           # Offer / StopOffer 生命周期时间线
│       ├── subscription_timeline.py    # Subscribe / Ack / Nack / Notification 时间线
│       ├── search_messages.py          # 按协议字段、IP 和时间范围检索报文
│       ├── message_detail.py           # 查询单条报文 Header、SD 和 Payload 解析树
│       ├── notification_statistics.py  # Notification 间隔与信号字段统计
│       └── payload_field.py             # 按字段路径读取单个深层 Payload 节点
│
├── core/                               # 全链路解析编排层（不依赖 Web）
│   └── pipeline.py                     # ARXML 编译 → PCAP 解析 → Payload 反序列化
│
├── presentation/                       # 展示/API 视图模型层
│   ├── message_view.py                 # 原始数据展示树：msg dict → FieldNode
│   └── api_views.py                    # Message summary/detail/raw_view/message_kind
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
│   ├── sd_diagnostic.py                # SD 订阅诊断（Offer→Subscribe→Notify 链路）
│   └── queries/                        # 页面 API 与 AI 共用的会话级查询层
│       ├── __init__.py                 # SessionQueries 聚合入口和兼容补建
│       ├── evidence.py                 # Header 真值、时间过滤和报文证据
│       ├── message_query.py            # 消息只读索引与组合检索
│       ├── sd_query.py                 # SD Entry 分类和 Service 索引
│       ├── service_query.py            # ARXML/抓包/诊断服务查询
│       ├── offer_query.py              # Offer 生命周期查询
│       ├── subscription_query.py       # 订阅报告和生命周期查询
│       └── signal_query.py             # Notification、曲线与 Payload 字段查询
│
├── utils/                              # 工具模块
│   └── logger.py                       # 统一日志：控制台 + RotatingFileHandler
│
├── web/                                # Web 界面（FastAPI + Vue 3）
│   ├── start.py                        # 一键启动（自动构建前端 + uvicorn）
│   ├── backend/
│   │   ├── app.py                      # FastAPI 入口 + API 路由 + 静态文件
│   │   └── handlers/
│   │       ├── analysis.py             # 上传/session 适配，调用 core + presentation
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
`common.py` → `strategies.py` → `parser.py`

### core / presentation
`core/pipeline.py` → `presentation/message_view.py` → `presentation/api_views.py`

### arxml_parsers
`arxml_parser.py` → `type_factory.py` → `service_registry.py`

### deserialization
`field_node.py` → `engine.py`

### analysis
`signal_utils.py` → `sd_diagnostic.py` → `queries/__init__.py` → 各领域 Query

### assistant
`config.py` → `provider.py` → `service.py` → `tools/__init__.py` → 各 Tool 文件

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

### AI 分析助手（MVP）

页面右上角的 `AI 助手` 会打开当前解析会话的侧边问答面板。面板左边缘可以
拖动调节宽度，回答按经过安全清理的 GFM Markdown 渲染。当前提供八个只读 Tool：

| Tool | 作用 |
|------|------|
| `get_subscription_status` | 汇总 Offer、Subscribe、Ack、Nack 和 Notification 诊断 |
| `find_service` | 按十六进制 ID、十进制 ID 或 ARXML 名称查找服务 |
| `get_offer_timeline` | 查询 Offer、StopOffer、Instance、TTL 和发布 ECU 时间线 |
| `get_subscription_timeline` | 查询 Subscribe、Ack、Nack 和关联 Notification 时间线 |
| `search_messages` | 按服务、方法、报文类型、IP、SD Entry 和时间范围过滤报文 |
| `get_message_detail` | 读取指定报文的 Header、SD、Payload 和反序列化树 |
| `get_notification_statistics` | 统计 Notification 数量、间隔、端点和可选信号字段 |
| `get_payload_field` | 按报文索引和字段路径读取单个深层 Payload 节点 |

页面默认填充 DeepSeek 官方 OpenAI-compatible 地址和 `deepseek-v4-flash` 模型。
不同服务商签发的 API Key 不通用，切换服务商时必须同时检查 API Key、API 地址
和模型名称。API Key 只保存在后端进程内存，不会写入浏览器存储或项目文件。

也可以在启动服务前通过环境变量配置 DeepSeek：

```bash
export DEEPSEEK_API_KEY="your-deepseek-api-key"
export AI_API_BASE="https://api.deepseek.com"
export AI_MODEL="deepseek-v4-flash"
python run.py web
```

兼容接口需要实现 `POST {AI_API_BASE}/chat/completions` 并支持 Tool Calling。
远程部署时应使用 HTTPS，并在后续加入用户认证和独立密钥存储。后续功能见
[`TODO.md`](TODO.md)。

#### Assistant 目录结构

```text
assistant/
├── __init__.py
├── config.py
├── navigation.py
├── provider.py
├── schemas.py
├── service.py
├── tool_support.py
└── tools/
    ├── __init__.py
    ├── subscription_status.py
    ├── find_service.py
    ├── offer_timeline.py
    ├── subscription_timeline.py
    ├── search_messages.py
    ├── message_detail.py
    ├── notification_statistics.py
    └── payload_field.py
```

| 文件或目录 | 职责 |
|------------|------|
| `assistant/__init__.py` | 稳定的包入口，供 FastAPI 导入助手服务，不暴露内部实现细节 |
| `assistant/config.py` | 合并页面运行时配置、环境变量和默认值；API Key 仅驻留当前进程内存 |
| `assistant/navigation.py` | 从 Tool 结构化结果提取报文、Service、EventGroup 和信号时序导航参数 |
| `assistant/provider.py` | 构造 OpenAI-compatible Chat Completions 请求并统一转换连接错误 |
| `assistant/schemas.py` | 校验模型配置和对话请求长度、类型等 API 边界 |
| `assistant/service.py` | 绑定解析会话与对话历史，注入系统提示词，循环处理模型 Tool Calling |
| `assistant/tool_support.py` | 集中实现 ID/时间/布尔参数解析、返回量限制、名称查询和报文证据格式 |
| `assistant/tools/__init__.py` | 向模型提供 Tool JSON Schema，并通过显式白名单把调用分发到只读函数 |
| `assistant/tools/*.py` | 每个文件实现一个独立查询能力，读取服务端注入的解析会话，不接受任意文件路径 |

调用链如下：

```text
AiAssistant.vue
  -> POST /api/session/{session_id}/assistant/chat/stream（NDJSON 进度事件）
    -> assistant.service.chat
      -> assistant.provider.create_chat_completion
        -> 模型选择 Tool 并填写参数
      -> assistant.tools.execute_tool（白名单分发）
        -> analysis.queries.SessionQueries（会话级只读索引）
          -> session messages / SD records / ServiceRegistry
      -> 模型根据 Tool 证据生成 Markdown 回答
      -> assistant.navigation.collect_navigation_links
        -> 前端证据按钮跳转报文树、订阅诊断或信号时序
```

Tool 执行期间会实时显示查询阶段。最终回答中的稳定 Markdown 锚点以及 Tool
返回的结构化证据按钮都支持联动：报文证据打开对应消息与解析树，Service 和
EventGroup 打开订阅诊断并定位目标，带时间范围的信号证据打开时序图并缩放。
原同步 `/assistant/chat` 接口仍保留，用于兼容已有调用方。

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
| **管道层** | `core/pipeline.py` | 统一编排 ARXML / PCAP / Payload，独立于 Web |
| **数据视图分离** | `presentation/` | 展示树和 API DTO 与解析逻辑解耦 |
| **胶水层** | `web/backend/handlers/` | handler 只处理上传、session、HTTP 适配 |

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
