# AI 问答助手 LangChain / LangGraph 重构 TODO

## 1. 重构结论

本次不再维护自研 Agent 工作流，也不设计 Legacy/LangGraph 双运行时。直接将 AI 问答
主链路迁移到 LangChain 1.x 与 LangGraph，现有 `_run_tool_loop`、自研模型消息循环和
重复的工作流代码在新链路通过回归测试后删除。

第一批重构先完成框架、Tool Calling、ReAct、Reflection 和 Web 主链路切换；上下文工程、
短期/长期记忆、Checkpoint 深化、可观测性等能力在主框架稳定后继续建设。

RAG 暂不纳入本轮重构。当前核心数据是 PCAP、SOME/IP-SD、ARXML 和 Payload 的结构化
结果，使用精确查询 Tool 比向量检索更可靠。以后只有在引入协议规范、诊断手册等
非结构化知识库时，再单独评估 Retrieval/RAG。

## 2. 目标技术架构

| 能力 | 目标实现 |
|------|----------|
| Agent 主框架 | LangGraph `StateGraph` |
| 动态推理与工具选择 | LangChain `create_agent` ReAct 子图 |
| Reflection | LangGraph evaluator-optimizer 子图 |
| 模型接入 | `ChatDeepSeek`、`ChatOpenAI` 及兼容 ChatModel |
| Tool Calling | LangChain `StructuredTool` / `@tool` |
| 参数与回答约束 | Pydantic Schema + Structured Output |
| 运行时依赖 | LangChain `Runtime` / `ToolRuntime` |
| 横切治理 | LangChain Middleware |
| 状态与条件路由 | LangGraph State、Node、Conditional Edge |
| 流式输出 | LangGraph Stream Events → 现有 NDJSON |
| 后续短期记忆 | LangGraph Checkpointer |
| 后续长期记忆 | LangGraph Store |
| 后续可观测性 | LangSmith 或 OpenTelemetry |

目标调用链：

```text
FastAPI chat / stream
        |
        v
LangGraph SOME/IP Diagnostic Graph
        |
        +--> bootstrap             校验会话、模型、权限和预算
        +--> classify              识别意图与 SOME/IP 实体
        +--> diagnostic_agent      受约束 ReAct：Model <-> Tools
        +--> collect_evidence      汇总 Tool 证据
        +--> draft_answer          生成结构化初稿
        +--> deterministic_guard   确定性证据与链接校验
        +--> reflect_answer        LLM 评审初稿
        +--> revise / finish       限次修正或完成
        |
        v
Structured Answer + Markdown + Navigation
```

## 3. 重构边界

必须保留：

- `someip/analysis/queries/`：页面和 AI 共用的唯一事实查询层。
- `assistant/tools/*.py`：现有十四个 SOME/IP 领域查询实现。
- Tool 白名单、参数限制、结果大小限制、跨会话授权和取消能力。
- 证据链接、Markdown、流式输出和前端页面联动。
- DeepSeek、OpenAI-compatible 模型配置能力。

需要替换：

- `assistant/application/service.py::_run_tool_loop`。
- 自研 assistant/tool 消息拼装和模型循环终止逻辑。
- 自研 Provider HTTP 请求实现，优先迁移到 LangChain 官方 ChatModel。
- 分散在 Service 中的 Tool 重试、模型重试和生命周期控制。
- 最终仅依赖 Prompt 约束的自由文本回答流程。

本轮明确不做：

- RAG、向量数据库、Embedding 和文档切分。
- 多 Agent 协作、Supervisor、GraphRAG 和自动生成 Tool。
- 让模型直接访问 PCAP 文件、ARXML 文件、Shell 或数据库连接。
- 在主框架迁移前大规模重写上下文和记忆系统。

## 4. 当前能力基线

- [x] 十四个 SOME/IP/SD/ARXML/Payload 只读 Tools 已完成。
- [x] 页面和 AI Tool 已复用 `SessionQueries` 统一查询层。
- [x] 已有 Tool Schema、白名单、参数校验、调用预算和结果截断。
- [x] 已有 DeepSeek 和 OpenAI-compatible 模型配置。
- [x] 已有 NDJSON 流式文本、Tool 进度、请求取消和失败重试。
- [x] 已有 Token 预算、滚动摘要和可选对话持久化。
- [x] 已有证据校验、导航链接校验和固定诊断评测集。
- [x] 已有 Tool、Provider、流式、可靠性和查询层测试。

这些能力是迁移验收基线，不代表其内部实现必须保留。

## 5. 第一阶段：直接引入框架和模型适配

目标：项目开始直接依赖 LangChain/LangGraph，并建立新的 Agent 目录。

- [x] 新增并锁定后端依赖：`langchain`、`langchain-core`、`langgraph`、
  `langchain-deepseek`、`langchain-openai`。
- [x] 建立统一依赖文件和版本锁定机制，记录 Python 版本兼容范围。
- [x] 新增 `assistant/agent/`：`state.py`、`context.py`、`graph.py`、`routing.py`、`nodes/`。
- [x] 新增 `assistant/integrations/langchain/`：`models.py`、`tools.py`、`events.py`。
- [x] 使用 `ChatDeepSeek` 接入 `deepseek-chat`，明确 `deepseek-reasoner` 不进入 Tool Calling 主链路。
- [x] 使用 `ChatOpenAI` 接入 OpenAI 和标准 OpenAI-compatible Chat Completions 服务。
- [x] 建立 `ModelFactory`，根据 Provider 返回标准 `BaseChatModel`，不向上层暴露厂商协议。
- [x] 通过离线标准协议测试验证流式、Structured Output 和模拟 Tool Calling。
- [x] 将 API Key、base URL、模型名、超时、重试和 Token 上限统一映射到 ChatModel 配置。
- [x] 增加模型适配单元测试，不再使用真实 HTTP 请求作为普通测试前提。

验收：标准 ChatModel 能完成流式问答、结构化输出和一次模拟 Tool Calling。

## 6. 第二阶段：将现有 Tools 迁移为 LangChain Tools

目标：Tool 先框架化，领域查询逻辑保持不变。

- [x] 为十四个 Tool 分别定义 Pydantic `args_schema`。
- [x] 使用 `StructuredTool` 或统一 Tool Factory 包装现有 `execute_tool`。
- [x] Tool 描述统一说明用途、调用条件、ID 格式、返回范围、证据类型和限制。
- [x] 使用 `ToolRuntime` 注入 `session_id`、授权对比会话、取消信号和执行预算。
- [x] 模型可见参数中禁止出现查询对象、文件路径、API Key 和服务端内部状态。
- [x] 将现有 `ToolExecutor` 治理能力接入 `wrap_tool_call` Middleware；请求级执行器继续
  负责原子化累计预算和超时控制，避免在适配层复制执行逻辑。
- [x] Middleware 继续执行白名单、Pydantic 校验、超时、取消、总预算和结果大小治理。
- [x] Tool 返回统一结构：`summary`、`data`、`evidence`、`warnings`、`truncated`、`error`。
- [x] 使用 Tool artifact 保存前端需要的完整证据；模型只接收有限摘要。
- [x] 为大结果加入分页、字段选择和明确截断信息。
- [x] 增加 LangChain Tool 与原 Tool 的契约对比测试。

验收：十四个 Tool 都能被 LangChain 调用，返回事实与现有实现完全一致。

## 7. 第三阶段：建立 LangGraph + ReAct 主图

目标：用 LangGraph 完全接管当前自研 Tool Calling 循环。

- [ ] 定义 `SomeIpAgentState`，至少包含 messages、intent、entities、tool_trace、
  evidence、draft_answer、reflection、final_answer、status、budget 和 error。
- [ ] 定义 `SomeIpAgentContext`，注入当前会话、允许访问的会话、模型配置和取消信号。
- [ ] 实现 `bootstrap` 节点：校验解析会话、问题、模型能力、权限和执行预算。
- [ ] 实现 `classify` 节点：使用 Structured Output 识别意图、Service/Method/EventGroup、
  IP、字段路径、时间范围以及是否需要 Tool。
- [ ] 根据意图动态选择 Tool 子集，避免每轮向模型暴露全部 Tool Schema。
- [ ] 使用 LangChain `create_agent` 构建 ReAct 子图，负责模型决策、Tool Calling 和 ToolMessage。
- [ ] 将 ReAct Agent 嵌入外层 `StateGraph`，外层负责确定性前后处理。
- [ ] 使用条件边处理 direct_answer、use_tools、clarify、partial_failure、cancelled 和 failed。
- [ ] 对重复 Tool、空结果、错误参数和部分失败建立明确路由。
- [ ] 设置最大模型轮次、最大 Tool 次数、Tool 总耗时、结果字节和 Token 硬限制。
- [ ] 将 Tool 证据从消息中抽取为独立 State 字段，避免只能从自然语言恢复证据。
- [ ] 为每个 Node、Edge 和完整 Graph 增加测试。

验收：新 Graph 能完成无 Tool、单 Tool、多 Tool、参数修复、部分失败和取消场景。

## 8. 第四阶段：加入 Reflection 子图

目标：在最终回答输出前，对事实覆盖、证据和推断边界进行自动评审和有限修正。

Reflection 采用 evaluator-optimizer 模式，不保存或展示模型隐藏思维过程，只保存结构化
评审结果和修正建议。

- [ ] 定义 `ReflectionResult` Schema：passed、score、missing_facts、unsupported_claims、
  evidence_gaps、format_issues、revision_instructions、needs_more_tools。
- [ ] 先执行确定性 Guard：Schema、证据 ID、报文索引、Service/EventGroup 和导航链接校验。
- [ ] 只有复杂诊断、跨会话对比、异常归因和报告类回答进入 LLM Reflection。
- [ ] 模型身份、配置查询、简单字段读取等低风险回答跳过 Reflection。
- [ ] Reflection 必须根据用户问题、结构化初稿和本轮证据评审，不能引入新事实。
- [ ] 若只是表达或结构问题，进入 `revise_answer` 节点修正回答。
- [ ] 若缺少必要事实且仍有预算，只允许返回 `diagnostic_agent` 补充一次 Tool 查询。
- [ ] 默认最多一次 Reflection 修正，硬上限两次，达到上限后输出带警告的部分结果。
- [ ] 防止评审器和生成器互相无限否定；相同反馈不得重复进入修正循环。
- [ ] 记录 Reflection 次数、评分、失败原因和新增 Tool 次数，不记录隐藏推理文本。
- [ ] 增加 Reflection 通过、修正、补充 Tool、预算耗尽和循环保护测试。

验收：固定评测集中，证据覆盖率和无依据结论率优于当前实现，延迟和 Token 增量可量化。

## 9. 第五阶段：接管 Web 主链路并删除旧工作流

目标：新 Graph 成为唯一生产调用链，不保留运行时切换开关。

- [ ] 将 `chat` 和 `chat_stream` 改为调用编译后的 LangGraph。
- [ ] 使用 LangGraph Stream Events 适配现有 NDJSON：context、tool_start、tool_end、
  text_delta、text_reset、completed、cancelled、error。
- [ ] 保持现有 FastAPI 路由、请求参数和前端返回字段兼容。
- [ ] 将 LangGraph run_id、node、sequence 和状态加入脱敏运行记录。
- [ ] 将现有请求取消信号接入 Graph、模型和 Tool 节点。
- [ ] 使用完整固定评测集和真实 PCAP/ARXML 执行回归。
- [ ] 删除 `_run_tool_loop` 及只为旧循环服务的消息拼装代码。
- [ ] 删除自研 Provider HTTP 调用和已被 ChatModel 替代的重复代码。
- [ ] 清理失效测试，保留并迁移所有行为测试。
- [ ] 更新 README 的目录树、调用链、配置和 Agent Graph 图。

验收：Web AI 助手只运行 LangGraph，现有对话、Tool 进度、取消和证据跳转功能不回退。

## 10. 第六阶段：上下文工程优化

目标：在主框架稳定后，优化每轮模型真正看到的上下文。

- [ ] 区分 Runtime Context、Graph State、Model Context 和 Tool Context。
- [ ] 使用 Middleware 动态构建 System Prompt、消息、Tool 子集和回答格式。
- [ ] 只向模型注入当前问题需要的会话摘要、领域实体和证据。
- [ ] 使用 Token 计数进行消息裁剪，优先保留系统规则、当前问题和关键证据。
- [ ] 使用 Summarization Middleware 替换当前简单滚动摘要。
- [ ] 结构化摘要保存用户目标、已确认事实、推断、未决项、最近实体和证据引用。
- [ ] 实现 Service、Method/Event、EventGroup、ECU、字段路径和时间范围的实体状态。
- [ ] 实现“这个服务”“刚才的事件”等指代消解，无法确定时进入 clarify 节点。
- [ ] 对 Tool 结果实施摘要、分页和生命周期清理，避免上下文持续膨胀。
- [ ] 增加长对话、多主题切换和上下文污染评测。

验收：长对话不超上下文窗口、不丢关键实体，平均输入 Token 和延迟低于迁移初版。

## 11. 第七阶段：Checkpoint 与记忆

目标：用 LangGraph 原生状态持久化逐步替代现有对话存储。

- [ ] 使用 `thread_id = session_id:conversation_id` 隔离对话线程。
- [ ] 单机环境接入 SQLite Checkpointer，支持节点级状态保存和恢复。
- [ ] 将现有可选“保存对话”映射为 Checkpoint 持久化策略。
- [ ] 支持页面关闭释放临时线程，持久记录按用户选择保留。
- [ ] 支持失败恢复、请求取消终态和 Checkpoint 删除。
- [ ] 从 `assistant/conversation/store.py` 迁移历史记录，并提供一次性兼容读取。
- [ ] 使用 LangGraph Store 设计长期记忆命名空间，但默认不开启自动写入。
- [ ] 长期记忆只允许保存用户明确授权的项目术语、偏好和已确认结论。
- [ ] 禁止长期保存 API Key、完整 Payload、完整 Tool 结果和未经确认的模型推断。
- [ ] 为未来多用户部署预留 PostgreSQL Checkpointer/Store。

验收：临时和持久对话生命周期符合当前产品规则，服务重启后可恢复指定线程且不串会话。

## 12. 第八阶段：可靠性、安全与可观测性

- [ ] 使用 Model/Tool Middleware 实现超时、指数退避、重试、熔断和错误归一化。
- [ ] PCAP、ARXML 和 Tool 内容全部视为不可信数据，增加 Prompt Injection Guard。
- [ ] 继续执行会话白名单、Tool 白名单、参数 Schema 和结果大小限制。
- [ ] API Key、完整 Prompt、原始 Payload 和 Tool 原始结果禁止进入普通日志。
- [ ] 接入 LangSmith 或 OpenTelemetry，默认仅记录脱敏 Trace 和指标。
- [ ] 记录 Graph Node、模型轮次、Tool、Reflection、Token、耗时、重试和最终状态。
- [ ] 当前只读 Tool 不增加 Human-in-the-loop；未来出现写操作时使用 `interrupt` 审批。
- [ ] 增加并发、超时、取消、恢复、越权、提示词注入和敏感信息测试。

验收：每次 Graph Run 可追踪，异常可解释，未授权调用为零，敏感正文不外泄。

## 13. 第九阶段：评测与质量门禁

- [ ] 扩展现有 Golden Cases，覆盖 Offer 冲突、无 Offer、无 Ack、Nack、无通知、
  Request/Response、深层 Payload、ARXML 和跨会话对比。
- [ ] 评测 Tool 选择率、参数正确率、事实准确率、证据覆盖率和无依据结论率。
- [ ] 评测 Reflection 修正成功率、误判率、额外延迟和 Token 成本。
- [ ] 评测 Agent 轨迹：重复 Tool、无效 Tool、越权 Tool、过早结束和循环次数。
- [ ] 对 DeepSeek 与 OpenAI-compatible 模型执行相同回归集。
- [ ] 将 Prompt、Graph、Tool Schema、Reflection Schema、模型和评测集版本化。
- [ ] 建立合并门禁：核心事实不能回退、导航链接必须有效、未授权调用必须为零。

验收：框架、Prompt、Tool 或模型变更都能输出可比较的质量报告。

## 14. RAG 决策

当前结论：不实施 RAG。

- PCAP、SD、ARXML 和 Payload 都可以通过精确索引和领域 Tool 查询。
- Service ID、Method ID、EventGroup、字段路径和报文索引不适合使用向量相似度查询。
- 当前问题的重点是 Agent 编排、Tool 可靠性和证据闭环，而不是缺少外部知识召回。

以后满足以下条件时再新增独立 RAG TODO：

- 需要查询 SOME/IP 规范、企业诊断手册、故障案例或自然语言字段说明。
- 文档数量已经无法通过静态 Prompt 或普通关键词查询管理。
- 已建立文档版权、版本、权限、引用和更新机制。
- 离线评测证明 RAG 对回答准确率有明确提升。

## 15. 实施顺序

第一批直接重构：

1. 第一阶段：框架与 ChatModel。
2. 第二阶段：LangChain Tools。
3. 第三阶段：LangGraph + ReAct。
4. 第四阶段：Reflection。
5. 第五阶段：接管 Web 并删除旧循环。

主框架完成后继续：

6. 第六阶段：上下文工程。
7. 第七阶段：Checkpoint 与记忆。
8. 第八阶段：安全与可观测性。
9. 第九阶段：持续评测和质量门禁。

## 16. 禁止事项

- [ ] 不保留 Legacy/LangGraph 运行时切换，迁移完成后旧循环必须删除。
- [ ] 不把 SOME/IP 查询实现复制到 Graph Node、Prompt 或 Tool Adapter。
- [ ] 不让模型直接访问文件系统、Shell、数据库连接、API Key 或未授权会话。
- [ ] 不把完整 PCAP、ARXML 或反序列化 JSON 放入 Graph State 或模型上下文。
- [ ] Reflection 不输出、不持久化模型隐藏思维过程，只保留结构化评审结果。
- [ ] Reflection 必须有限次、可中止并受 Token/时间预算控制。
- [ ] 当前不引入 RAG、多 Agent、Supervisor、GraphRAG 和自动长期记忆。
