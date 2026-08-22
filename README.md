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
├── assistant/                          # AI 问答编排层
│   ├── __init__.py                     # 唯一公共入口，屏蔽内部目录变化
│   ├── agent/                          # LangGraph State、路由与图节点
│   ├── integrations/langchain/         # ChatModel、StructuredTool 和 Middleware 适配
│   ├── application/                    # 会话服务与唯一 LangGraph 生产运行器
│   ├── contracts/                      # FastAPI 请求参数契约
│   ├── llm/                            # 不含调用逻辑的模型运行配置
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
`application/` → `agent/` → `integrations/langchain/` → `execution/tool_executor.py` → `tools/registry.py` → 各 Tool 文件

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

## AI 助手模块

`assistant/` 是独立的 SOME/IP 问答模块。Web 只调用它的公共入口，模块通过只读
Tool 查询现有解析结果，不直接读取 PCAP/ARXML 文件，也不包含协议解析实现。

### 目录结构

```text
assistant/
├── __init__.py                  # 对外公共入口
├── application/                 # Web 用例层：问答、流式响应、会话生命周期
│   ├── service.py
│   └── graph_runtime.py
├── agent/                       # LangGraph 状态图与单一职责节点
│   ├── graph.py
│   ├── state.py
│   ├── intent.py
│   ├── reflection.py
│   └── nodes/
├── integrations/langchain/      # LangChain/模型/Tool/流事件适配
│   ├── models.py
│   ├── runtime.py
│   ├── tools.py
│   ├── middleware.py
│   └── events.py
├── tools/                       # SOME/IP 只读领域工具，一项能力一个文件
│   ├── registry.py
│   ├── support.py
│   └── *.py
├── execution/                   # Tool 预算、超时、取消和脱敏运行记录
├── answering/                   # Prompt、回答边界和导航证据校验
├── conversation/                # Token 预算、摘要和可选对话持久化
├── contracts/                   # Web 请求的 Pydantic 契约
├── llm/                         # 与框架无关的模型运行配置
└── evaluation/                  # 固定诊断评测用例，不进入生产运行链路
```

### 职责边界

| 部分 | 只负责什么 |
|------|------------|
| `application` | 接收一次问答，准备会话上下文，运行 Graph，兼容同步与 NDJSON 返回 |
| `agent` | 编排分类、ReAct、证据收集、Guard、Reflection 和最终回答 |
| `integrations/langchain` | 把模型、Runtime、StructuredTool 和 LangGraph 事件接入项目 |
| `tools` | 把统一查询层封装成模型可调用的只读领域能力 |
| `execution` | 执行参数校验、次数/时间/大小限制、取消和审计 |
| `answering` | 约束事实与推断，校验 Markdown 页面导航证据 |
| `conversation` | 管理短期上下文预算和用户可选的对话保存 |
| `contracts`、`llm` | 保存稳定的请求契约和模型配置，不包含工作流 |
| `evaluation` | 保存离线质量基线，与生产代码隔离 |

这些目录不按“功能多少”划分，而按依赖变化原因划分。当前不需要继续拆分；把它们
合并回 `service.py` 会重新混合 Web、Agent、模型协议和领域查询，反而更难阅读。

### 运行链路

```text
Web / FastAPI
  -> application
    -> agent (LangGraph)
      -> integrations/langchain
        -> execution
          -> tools
            -> someip.analysis.queries
      -> answering
    -> conversation
```

Graph 主流程保持为一条有限状态链：

```text
bootstrap -> classify
  ├─ direct answer -> guard -> finish
  ├─ clarify -> finish
  └─ ReAct -> tools -> evidence -> draft -> guard
                                      └─ optional reflection/revision -> finish
```

复杂诊断才进入 Reflection；简单查询直接结束。Reflection 默认最多一次，补充 Tool
查询最多一次。项目不保留旧模型循环或 Legacy/LangGraph 切换。

Tool 能力覆盖 SD/订阅诊断、报文与 Payload 查询、ARXML 定义、Request/Response、
ECU 拓扑和已授权会话比较。每个 Tool 只能访问服务端注入的解析会话和白名单。

页面右上角的 `AI 助手` 打开侧边问答面板，回答以 GFM Markdown 渲染。API Key 仅
保存在后端进程内存；启用解析记录持久化后，用户仍需单独选择是否保存对话。

模型支持 DeepSeek 和通用 OpenAI-compatible 接口，兼容端点需实现 Tool Calling。
可通过页面配置，也可以在启动前设置：

```bash
export DEEPSEEK_API_KEY="your-deepseek-api-key"
export AI_API_BASE="https://api.deepseek.com"
export AI_MODEL="deepseek-chat"
python run.py web
```

运行预算可通过 `AI_MAX_MODEL_ROUNDS`、`AI_MAX_TOOL_CALLS`、
`AI_TOOL_TIMEOUT_SECONDS`、`AI_TOOL_TOTAL_TIMEOUT_SECONDS`、
`AI_TOOL_RESULT_MAX_BYTES` 和 `AI_TOOL_RESULTS_TOTAL_MAX_BYTES` 调整。默认值见
`assistant/execution/tool_executor.py`，后续工作见 [`TODO.md`](TODO.md)。

## 命令行调试

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
