# SOME/IP Dissector

基于 Python 的 SOME/IP（Scalable service-Oriented MiddlewarE over IP）协议解析工具链。
覆盖 PCAP 报文捕获 → SOME/IP 头部解析 → SOME/IP-SD 服务发现 → ARXML 服务定义编译
→ 二进制 Payload 反序列化 → Web 可视化的 **全链路分析**。

---

## 环境准备

### 依赖安装

```bash
pip install scapy lxml typing_extensions
pip install fastapi uvicorn python-multipart aiofiles
```

| 依赖 | 用途 |
|------|------|
| `scapy` | PCAP 读取、SOME/IP 与 SOME/IP-SD 协议栈 |
| `lxml` | ARXML 文件解析（XPath + 命名空间） |
| `fastapi` / `uvicorn` | Web 后端 API 服务 |
| `python-multipart` | 文件上传表单解析 |
| `typing_extensions` | Python < 3.11 的 `NotRequired` 兼容 |

### 前端构建（Node.js）

```bash
cd web/frontend && npm install && npm run build
```

> 如未构建，`web/start.py` 会自动执行。

---

## 项目架构

```
someip_dissector/
│
├── pcap_parsers/                       # SOME/IP 报文解析
│   ├── common.py                       # TypedDict 类型、校验、SD 常量、message_type_label()
│   ├── strategies.py                   # 策略模式：UDP 单包 / TCP 流重组
│   ├── parser.py                       # 调度器：遍历帧 → 分发策略 → 内联 SD 解析
│   └── message_view.py                 # 原始数据展示树：msg dict → FieldNode（供前端）
│
├── datatypes/                          # 共享数据类型体系
│   └── types.py                        # DataType 类族（BaseType / BoolType /
│                                       #   StringType / StructureType / ArrayType）
│
├── arxml_parsers/                      # ARXML 服务定义编译
│   ├── arxml_parser.py                 # lxml 提取 SW-BASE-TYPE、STD-CPP 类型、
│   │                                   #   SERVICE-INTERFACE、SOME/IP 部署
│   ├── type_factory.py                 # Factory + Builder 策略模式 → DataType 对象池
│   ├── service_registry.py             # Registry 模式：O(1) 查表 (srv, method, dir) → type_path
│   └── exporter.py                     # 中间产物 JSON 导出
│
├── deserialization/                    # 二进制 Payload 反序列化
│   ├── engine.py                       # 反序列化引擎：ID 查表 → 类型匹配 → 递归解析
│   └── field_node.py                   # 解析结果树节点（leaf / container，含 meta_kind 标记）
│
├── utils/                              # 工具模块
│   └── logger.py                       # 统一日志：控制台 + RotatingFileHandler
│
├── web/                                # Web 界面（FastAPI + Vue 3）
│   ├── start.py                        # 一键启动（自动构建前端 + uvicorn）
│   ├── backend/
│   │   ├── app.py                      # FastAPI 入口 + 静态文件挂载 + lifespan 清理
│   │   └── handlers/
│   │       ├── analysis.py             # 管道编排 + 会话管理 + API 格式化
│   │       └── upload.py               # 异步文件上传 + 校验
│   └── frontend/
│       ├── src/
│       │   ├── App.vue                 # 单页布局（上传栏 + 进度条 + 分割面板）
│       │   ├── api/index.js            # Axios API 封装
│       │   └── components/
│       │       ├── UploadBar.vue       # 拖拽上传 + 文件选择
│       │       ├── MessageTable.vue    # 消息列表（多关键字搜索 / 分页 / 三态状态列）
│       │       └── ParseTree.vue       # 双视图递归可折叠树（Raw PCAP + Deserialized）
│       ├── package.json
│       └── vite.config.js
│
├── test/                               # 单元测试
│   ├── test_pcap_parsers/              # sample.pcap + 测试脚本
│   ├── test_arxml_parsers/             # sample.arxml + 测试脚本
│   └── test_deserialization/           # 全链路反序列化测试
│
├── Tools/
│   └── generate_sample_pcap.py         # 纯 Python 生成测试用 pcap
│
├── main.py                             # CLI 批处理入口
├── sample.pcap / sample.arxml          # 示例输入文件
└── README.md
```

---

## 阅读顺序

### pcap_parsers
`common.py` → `strategies.py` → `parser.py` → `message_view.py`

### arxml_parsers
`datatypes/types.py` → `arxml_parser.py` → `type_factory.py` → `service_registry.py`

### deserialization
`field_node.py` → `engine.py`

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
            → 二进制 Payload 流式递归反序列化
              → 每条消息同时输出 raw_view（原始协议数据） + parsed（反序列化树）
```

---

## 快速开始

### CLI 批处理

```bash
python main.py
```

依次执行 PCAP 解析 → ARXML 编译 → 反序列化，结果输出到 `output/<timestamp>/`。

### Web 界面

```bash
python web/start.py
```

浏览器打开 **http://localhost:8000**：

1. 拖拽或选择 `pcap` + `arxml` 文件
2. 点击"开始解析"
3. 左侧消息列表支持多关键字搜索（空格分隔），状态列三态：
   - 🟢 已解析 — ARXML 类型匹配成功
   - 🟠 SD — SOME/IP-SD 服务发现报文
   - 🔴 未解析 — 类型未注册
4. 右侧双视图树：
   - **📦 Raw PCAP View** — 原始协议数据（Header 字段含偏移/字节数/hex；SD 含 Flags/Entries/Options）
   - **🔍 Deserialized** — ARXML 类型反序列化结果（仅已解析消息）
5. 关闭端口时自动清理 sessions 目录

| 地址 | 用途 |
|------|------|
| `http://localhost:8000` | Web 界面 |
| `http://localhost:8000/docs` | API 文档 (Swagger) |

### 运行测试

```bash
pytest test/ -v
```

---

## 设计模式

| 模式 | 应用位置 | 说明 |
|------|----------|------|
| **策略模式** | `pcap_parsers/strategies.py` | UDP / TCP 传输层解析可插拔扩展 |
| **工厂 + Builder** | `arxml_parsers/type_factory.py` | 按 CATEGORY 匹配 Builder，构建 DataType 对象池 |
| **注册表** | `arxml_parsers/service_registry.py` | O(1) 查表 (srv_id, method_id, dir) → type_path |
| **流式反序列化** | `deserialization/` | 返回 `(FieldNode, consumed_bytes)` 元组，自适应变长字段 |
| **递归组合** | `datatypes/types.py` | StructureType / ArrayType 内部嵌套 DataType，天然支持嵌套结构 |
| **数据视图分离** | `pcap_parsers/message_view.py` | 展示树构建与解析逻辑解耦；web 层仅做管道编排，不包含数据变换 |

## TODO LIST
* 信号时序多曲线同时显示
* Method Request/Response/Error 的正确性处理
* [Emergency] msg type 的全面性兼容，如msg_type = 0x22 目前没有支持
* [Feature] 双端pcap包的通信正确性检查