# SOME/IP Dissector

基于 Python 的 SOME/IP（Scalable service-Oriented MiddlewarE over IP）协议解析工具链。
覆盖 PCAP 报文捕获 → SOME/IP 头部解析 → SOME/IP-SD 服务发现 → TP 分片重组
→ ARXML 服务定义编译 → 二进制 Payload 反序列化 → Web 可视化的**全链路分析**。

---

## 环境准备

### 1. Python 依赖

```bash
python -m pip install -r requirements.txt
```

`requirements.txt` 固定了 Python 3.10 环境验证过的解析、Web 与 Agent 依赖版本，
避免 LangChain/LangGraph 独立升级后出现协议不兼容。

| 依赖 | 用途 |
|------|------|
| `scapy` | PCAP 读取、SOME/IP/SOME/IP-SD 协议栈 |
| `lxml` | ARXML 文件解析（XPath + 命名空间） |
| `fastapi` / `uvicorn` | Web 后端 API 服务 |
| `python-multipart` | 文件上传表单解析 |
| `aiofiles` | 异步文件 I/O |
| `typing_extensions` | Python < 3.11 的 `NotRequired` 兼容 |
| `langchain` / `langchain-core` | Agent、ChatModel、Tool 与 Middleware 标准接口 |
| `langgraph` | 有状态 Agent 工作流、条件边与后续 Checkpoint 支持 |
| `langchain-deepseek` | DeepSeek 官方 ChatModel 集成 |
| `langchain-openai` | OpenAI 与标准 OpenAI-compatible ChatModel 集成 |
| `tiktoken` | 模型上下文 Token 计数 |

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
├── someip/                             # SOME/IP 协议领域能力
│   ├── __init__.py                     # 协议领域包入口
│   ├── core/                           # ARXML → PCAP → Payload 全链路编排
│   │   └── pipeline.py
│   ├── pcap_parsers/                   # SOME/IP 报文解析、SD 与 TP 分片重组
│   │   ├── common.py                   # 类型、校验和 msg_type 统一映射
│   │   ├── strategies.py               # UDP 单包 / TCP 流策略
│   │   ├── parser.py                   # 解析调度器
│   │   └── message_view.py             # 展示视图兼容入口
│   ├── arxml_parsers/                  # ARXML 服务定义编译
│   │   ├── arxml_parser.py
│   │   ├── type_factory.py
│   │   ├── service_registry.py
│   │   └── exporter.py
│   ├── datatypes/                      # Payload 数据类型体系
│   │   └── types.py
│   ├── deserialization/                # 二进制 Payload 反序列化
│   │   ├── engine.py
│   │   └── field_node.py
│   ├── analysis/                       # 信号分析与 SD 诊断查询
│   │   ├── signal_utils.py
│   │   ├── sd_diagnostic.py
│   │   └── queries/                    # 页面与 AI 共用的会话级查询层
│   └── presentation/                   # 展示树和 API 视图模型
│       ├── message_view.py
│       └── api_views.py
│
├── assistant/                          # AI 问答编排层（不依赖具体 Web 页面）
│   ├── __init__.py                     # 唯一公共入口，屏蔽内部目录变化
│   ├── agent/                          # LangGraph State、Runtime Context 与图节点
│   ├── integrations/langchain/         # ChatModel、StructuredTool 和 Middleware 适配
│   ├── application/                    # 对话、流式事件与模型循环编排
│   ├── contracts/                      # FastAPI 请求参数契约
│   ├── llm/                            # 模型配置、调用门面和供应商适配器
│   ├── conversation/                   # 上下文预算、滚动摘要和对话存储
│   ├── execution/                      # Tool 预算、超时、取消和运行记录
│   ├── answering/                      # Prompt、回答契约和证据链接校验
│   ├── tools/                          # Tool 注册表、公共校验和独立查询工具
│   └── evaluation/                     # 固定诊断评测集和加载器
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

### someip/pcap_parsers
`common.py` → `strategies.py` → `parser.py`

### someip/core / presentation
`someip/core/pipeline.py` → `someip/presentation/message_view.py` → `someip/presentation/api_views.py`

### someip/arxml_parsers
`arxml_parser.py` → `type_factory.py` → `service_registry.py`

### someip/deserialization
`field_node.py` → `engine.py`

### someip/analysis
`signal_utils.py` → `sd_diagnostic.py` → `queries/__init__.py` → 各领域 Query

### assistant
`agent/` → `integrations/langchain/` → `execution/tool_executor.py` → `tools/registry.py` → 各 Tool 文件

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

### AI 分析助手

页面右上角的 `AI 助手` 会打开当前解析会话的侧边问答面板。面板左边缘可以
拖动调节宽度，回答按经过安全清理的 GFM Markdown 渲染。当前提供十四个只读 Tool：

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
| `get_request_response_trace` | 关联 Request/Response，统计响应时间、缺失响应和错误返回 |
| `get_ecu_service_topology` | 汇总 ECU 的服务角色、订阅和通信方向 |
| `get_arxml_definition` | 按服务和成员读取有限 ARXML 类型定义 |
| `search_payload_values` | 按字段路径、值、范围和时间检索反序列化结果 |
| `get_anomaly_details` | 按类型展开订阅诊断异常和代表证据 |
| `compare_sessions` | 比较明确授权记录的服务、Offer、订阅、通知和异常差异 |

跨会话比较默认关闭。用户必须在 AI 面板的“对比”菜单中明确勾选目标记录，
后端才会把对应 Session ID 加入当前请求白名单；模型不能枚举或访问未授权记录。

页面默认填充 DeepSeek 官方 OpenAI-compatible 地址和 `deepseek-v4-flash` 模型。
不同服务商签发的 API Key 不通用，切换服务商时必须同时检查 API Key、API 地址
和模型名称。API Key 只保存在后端进程内存，不会写入浏览器存储或项目文件。

模型配置还可以选择 `DeepSeek` 或通用 `OpenAI-compatible` Provider、上下文窗口、
最大输出 Token 和流式开关。“验证 Tool Calling”会产生一次最小模型请求，用于
检查当前模型是否返回强制 Tool Call，并在启用流式模式时同时验证 SSE 响应。
上下文窗口无法从所有兼容接口可靠读取，因此必须按供应商文档填写；后端会在
每次请求前预留 Tool Schema、最大输出和安全余量，超限时滚动摘要较早对话。

也可以在启动服务前通过环境变量配置 DeepSeek：

```bash
export DEEPSEEK_API_KEY="your-deepseek-api-key"
export AI_API_BASE="https://api.deepseek.com"
export AI_MODEL="deepseek-v4-flash"
python run.py web
```

第五阶段执行治理预算可以通过环境变量调整；未配置时使用下列默认值：

| 环境变量 | 默认值 | 作用 |
|----------|--------|------|
| `AI_MAX_MODEL_ROUNDS` | `5` | 单次问答最多模型轮数，防止持续 Tool Calling |
| `AI_MAX_TOOL_CALLS` | `12` | 单次问答最多 Tool 调用次数 |
| `AI_TOOL_TIMEOUT_SECONDS` | `8` | 单个 Tool 等待超时秒数 |
| `AI_TOOL_TOTAL_TIMEOUT_SECONDS` | `30` | 单次问答累计 Tool 等待预算 |
| `AI_TOOL_RESULT_MAX_BYTES` | `524288` | 单个 Tool 返回给模型的最大字节数 |
| `AI_TOOL_RESULTS_TOTAL_MAX_BYTES` | `2097152` | 单次问答累计 Tool 结果字节预算 |

Tool 超时、参数错误或结果超限不会丢弃已取得的证据；最终回答会追加“查询限制”。
每次问答的 `run` 字段和服务端 `assistant_run` 日志只包含轮次、耗时、结果大小与
Token 用量，不记录 API Key、用户问题、模型答案、System Prompt 或原始 Payload。

兼容接口需要实现 `POST {AI_API_BASE}/chat/completions` 并支持 Tool Calling。
远程部署时应使用 HTTPS，并在后续加入用户认证和独立密钥存储。后续功能见
[`TODO.md`](TODO.md)。

#### Assistant 目录结构

```text
assistant/
├── __init__.py
├── agent/
│   ├── context.py
│   ├── state.py
│   ├── routing.py
│   ├── graph.py
│   └── nodes/
├── integrations/
│   └── langchain/
│       ├── models.py
│       ├── tools.py
│       ├── tool_schemas.py
│       ├── tool_results.py
│       ├── middleware.py
│       └── events.py
├── application/
│   └── service.py
├── contracts/
│   └── requests.py
├── llm/
│   ├── config.py
│   ├── gateway.py
│   └── providers/
│       ├── base.py
│       ├── deepseek.py
│       ├── generic.py
│       ├── openai_compatible.py
│       └── registry.py
├── conversation/
│   ├── context_budget.py
│   └── store.py
├── execution/
│   ├── tool_executor.py
│   └── run_record.py
├── answering/
│   ├── navigation.py
│   └── prompts/
│       └── v1.py
├── evaluation/
│   ├── __init__.py
│   ├── loader.py
│   └── cases_v1.json
└── tools/
    ├── __init__.py
    ├── registry.py
    ├── support.py
    ├── subscription_status.py
    ├── find_service.py
    ├── offer_timeline.py
    ├── subscription_timeline.py
    ├── search_messages.py
    ├── message_detail.py
    ├── notification_statistics.py
    ├── payload_field.py
    ├── request_response_trace.py
    ├── ecu_service_topology.py
    ├── arxml_definition.py
    ├── payload_value_search.py
    ├── anomaly_details.py
    └── compare_sessions.py
```

| 文件或目录 | 职责 |
|------------|------|
| `assistant/__init__.py` | 稳定的包入口，供 FastAPI 导入助手服务，不暴露内部实现细节 |
| `assistant/agent/` | 定义 LangGraph State、条件路由和不进入模型消息的请求级 Runtime Context |
| `assistant/integrations/langchain/` | 适配标准 ChatModel 和十四个 StructuredTool，执行参数校验、结果分层及 Tool Middleware |
| `assistant/application/` | 绑定解析会话和对话历史，编排模型循环、流式事件、取消及答案后处理 |
| `assistant/contracts/` | 定义配置、聊天和持久化请求的 Pydantic 边界模型 |
| `assistant/llm/` | 管理模型配置、统一调用门面、能力探测和供应商适配器 |
| `assistant/conversation/` | 管理 Token 预算、滚动摘要与对话的可选原子持久化 |
| `assistant/execution/` | 管理 Tool 参数校验、超时、调用预算及不含敏感正文的运行记录 |
| `assistant/answering/` | 管理版本化 Prompt、事实与推断边界及模型导航链接校验 |
| `assistant/evaluation/` | 读取十二类固定诊断评测约束，包括必需事实、禁止推断和允许证据 |
| `assistant/tools/registry.py` | 汇总 Tool Schema，并通过显式白名单把调用分发到只读函数 |
| `assistant/tools/support.py` | 集中实现 ID/时间/布尔参数解析、返回量限制、名称查询和报文证据格式 |
| `assistant/tools/*.py` | 每个文件实现一个独立查询能力，读取服务端注入的解析会话，不接受任意文件路径 |

依赖方向固定为 `Web → assistant 公共入口 → application`。`application` 可以组合
其他子包，但 `llm`、`conversation`、`execution`、`answering`、`tools` 和
`evaluation` 不反向导入 `application`，避免模型协议、查询能力与 Web 编排重新耦合。

调用链如下：

```text
AiAssistant.vue
  -> POST /api/session/{session_id}/assistant/chat/stream（NDJSON 进度事件）
    -> assistant.application.service.chat
      -> assistant.llm.gateway.create_chat_completion
        -> 模型选择 Tool 并填写参数
      -> assistant.execution.tool_executor.ToolExecutor（预算、超时、参数与结果治理）
        -> assistant.tools.registry.execute_tool（白名单分发）
          -> someip.analysis.queries.SessionQueries（会话级只读索引）
            -> session messages / SD records / ServiceRegistry
      -> 模型根据 Tool 证据生成 Markdown 回答
      -> assistant.answering.navigation.validate_answer_navigation_links
        -> 前端证据按钮跳转报文树、订阅诊断或信号时序
```

Tool 执行期间会实时显示查询阶段。最终回答中的稳定 Markdown 锚点以及 Tool
返回的结构化证据按钮都支持联动：报文证据打开对应消息与解析树，Service 和
EventGroup 打开订阅诊断并定位目标，带时间范围的信号证据打开时序图并缩放。
原同步 `/assistant/chat` 接口仍保留，用于兼容已有调用方。

流式接口还会发送 `context`、`text_reset`、`text_delta`、`cancelled` 等事件。
前端可以停止活动请求或重试失败问题。解析记录已持久化时，AI 面板中的“对话不保存”
可切换为“对话已保存”；保存文件位于该记录的 `assistant/conversations.json`，其中
不包含 API Key、System Prompt、Tool 原始结果或完整 Payload。

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
| **策略模式** | `someip/pcap_parsers/strategies.py` | UDP / TCP 传输层解析可插拔 |
| **工厂 + Builder** | `someip/arxml_parsers/type_factory.py` | CATEGORY → Builder → DataType |
| **注册表** | `someip/arxml_parsers/service_registry.py` | O(1) 查表 + ID → 名称映射 |
| **流式反序列化** | `someip/deserialization/` | 返回 `(FieldNode, consumed_bytes)` |
| **递归组合** | `someip/datatypes/types.py` | Struct/Array 嵌套 DataType |
| **管道层** | `someip/core/pipeline.py` | 统一编排 ARXML / PCAP / Payload，独立于 Web |
| **数据视图分离** | `someip/presentation/` | 展示树和 API DTO 与解析逻辑解耦 |
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
