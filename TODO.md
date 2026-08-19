# AI 分析助手待办事项

## 第一阶段：完善现有 Tool（已完成）

- [x] 将订阅统计字段改为无歧义名称，并明确服务、EventGroup 和报文三种统计单位。
- [x] 为 Offer、Subscribe、Ack、Nack 和 Notification 返回报文证据。
- [x] 证据包含消息索引、PCAP 帧序号、时间戳、源/目标 IP 和 SD Entry 索引。
- [x] 区分抓包事实、项目关联规则和可能原因，避免把推断描述成线上字段。
- [x] 注入当前实际模型名称和 API 地址，正确回答模型身份。
- [x] 修复 EventGroup ID 已带 `0x8000` 时 Notification 被重复计数的问题。
- [x] 将 Offer 冲突判定修正为同一 `(Service ID, Instance ID)` 被多个 ECU 发布，避免合法多实例误报。
- [x] 将助手目录中原有英文模块说明和关键注释改为中文。

## 第二阶段：补充核心 Tools（已完成）

- [x] `get_subscription_status`：查询 Offer、Subscribe、Ack、Nack 和 Notification 总览。
- [x] `find_service`：通过十六进制 ID、十进制 ID 或 ARXML 名称查找服务。
- [x] `get_offer_timeline`：查询 Offer、StopOffer、TTL、Instance 和发布 ECU。
- [x] `get_subscription_timeline`：查询 Subscribe、StopSubscribe、Ack、Nack 和关联通知。
- [x] `search_messages`：按服务、方法、类型、IP、SD Entry、状态和时间检索报文。
- [x] `get_message_detail`：读取 Header、SD、Payload 和反序列化树，并限制大字段长度。
- [x] 使用服务端白名单注册全部 Tool，拒绝模型调用未注册函数。
- [x] 增加 Tool Schema、参数、证据、重复计数和白名单分发单元测试。

## 第三阶段：统一查询层（已完成）

- [x] 将页面 API 与 AI Tool 的共用查询逻辑抽取到 `someip/analysis/queries/`。
- [x] 增加服务、Offer、订阅、消息、信号和证据查询模块，避免重复遍历大型抓包。
- [x] 为会话建立只读索引，缓存 Service、Method、SD Entry、IP、状态和时间戳映射。
- [x] 增加 `get_notification_statistics`，支持通知间隔与信号字段数值统计。
- [x] 增加 `get_payload_field`，按字段路径读取深层 Payload，避免发送整棵解析树。
- [x] 让消息列表、订阅诊断、信号时序和 AI Tool 复用同一个会话查询对象。
- [x] 增加索引复用、非单调时间戳、页面同源数据和字段路径查询单元测试。

## 第四阶段：前端证据联动

- [x] 点击 AI 回答中的报文证据，跳转消息列表并展开解析树。
- [x] 点击 Service ID，打开订阅诊断中的对应服务。
- [x] 点击 EventGroup，展开客户端和 Ack 状态。
- [x] 点击时间范围，跳转信号时序页面并应用对应缩放范围。
- [x] 通过 NDJSON 事件流显示“正在查询 Offer 时间线”等 Tool 执行进度。

## 对话与模型接入

- [x] 将基础请求客户端扩展为 `assistant/llm/providers/` 可插拔适配层，支持 DeepSeek 和通用 OpenAI-compatible 接口。
- [x] 通过 NDJSON 实时输出模型文本、Tool 执行进度、Token 预算和最终结果。
- [x] 增加模型能力探测，验证 Tool Calling 与流式输出；上下文窗口由配置约束并在请求前校验。
- [x] 增加可插拔 Token 计数器；安装 `tiktoken` 时使用真实编码器，否则使用保守 Unicode 估算。
- [x] 为长对话增加有界滚动摘要，并将模型上下文历史与 UI 展示历史分离。
- [x] 允许持久化解析记录选择是否同时保存 AI 对话，API Key 和 Tool 原始结果不落盘。
- [x] 增加请求取消和失败问题重试功能。
- [ ] 为 DeepSeek、百炼和本地模型接入各供应商官方 Tokenizer，替代通用估算。

## 第五阶段：问答可靠性与执行治理（已完成）

> 目标：先让基础 Tool 的调用过程可限制、可观测、可评测，再继续增加工具数量。

- [x] 从 `assistant/application/service.py` 抽取独立 Tool 执行器，统一处理参数校验、超时、取消、结果大小和异常转换。
- [x] 为单次问答增加模型轮数、Tool 调用次数、单 Tool 耗时、累计 Tool 耗时和结果字节数预算。
- [x] Tool 达到预算或部分失败时返回可用的部分证据，并要求模型明确说明未完成的查询，避免整轮问答直接失败。
- [x] 为每次问答生成结构化运行记录，包含请求 ID、会话 ID、模型轮次、Tool 名称、耗时、结果大小和 Token 用量。
- [x] 运行记录禁止保存 API Key、完整 Payload、System Prompt 和未经脱敏的模型请求体。
- [x] 将系统提示词拆分为版本化模板，分别管理角色约束、事实与推断边界、Tool 使用规则和回答格式。
- [x] 增加回答契约：结论必须区分“抓包事实”“项目诊断规则”“可能原因”，关键结论必须关联结构化证据。
- [x] 检查模型生成的报文、Service 和 EventGroup 链接，丢弃无法由本轮 Tool 结果验证的链接。
- [x] 增加无 Tool 回答、Tool 参数错误、空结果、部分失败、超时、取消和模型循环调用的回归测试。
- [x] 建立第一版固定评测集，覆盖 Offer 冲突、无 Offer 订阅、无 Ack、Nack、订阅后无通知和正常链路。
- [x] 为评测集记录期望调用的 Tool、必须出现的事实、禁止出现的推断和允许的证据范围。

## 第六阶段：诊断 Tools 扩展（已完成）

- [x] `get_request_response_trace`：按 Client ID、Session ID、Service 和 Method 关联 Request/Response，统计响应时间、缺失响应和错误码。
- [x] `get_ecu_service_topology`：汇总 ECU/IP 的服务提供、服务消费、订阅关系和通信方向。
- [x] `get_arxml_definition`：查询 Service、Method、Event、EventGroup、字段路径和数据类型定义，不向模型发送整份 ARXML。
- [x] `search_payload_values`：按字段路径、值、范围和时间检索反序列化结果，并返回有限报文证据。
- [x] `get_anomaly_details`：按异常类型展开受影响服务、EventGroup、客户端、时间范围和代表报文。
- [x] `compare_sessions`：比较最多四组已解析记录的服务、Offer、订阅、通知数量和异常差异。
- [x] 为跨会话 Tool 增加显式会话白名单，模型只能访问用户在当前 AI 面板中明确选择的解析记录。
- [x] 为每个新增 Tool 延续“一文件一工具”，复用 `someip/analysis/queries/`；Payload 字段路径使用有界懒索引。
- [x] 为新增 Tool 补充 Schema、参数边界、结果上限、可用证据链接和真实 PCAP/ARXML 全链路回归。

## 第七阶段：上下文与知识增强（中期计划）

- [ ] 将滚动摘要升级为结构化会话摘要，分别保存用户目标、已确认事实、未解决问题和最近使用的 Service/EventGroup。
- [ ] 对“这个服务”“刚才的 EventGroup”等指代增加显式实体解析，无法唯一确定时要求用户澄清。
- [ ] 建立 ARXML 名称、字段说明和项目诊断规则的轻量检索层，为模型提供按需上下文而不是完整配置文件。
- [x] 支持用户选择多组解析记录后进行对比问答，默认仍严格绑定当前会话，避免跨抓包串数据。
- [ ] 支持把一次诊断问答整理为结构化报告，包含结论、证据、推断、未决项和后续排查建议。
- [ ] 支持导出 Markdown/JSON 诊断报告，并在导出前允许用户选择是否包含 IP、Payload 和 ARXML 名称。

## 第八阶段：模型与部署演进（长期计划）

- [ ] 增加 OpenAI、阿里云百炼和本地模型的独立 Provider，厂商适配器统一继承 `BaseProvider` 并组合协议客户端。
- [ ] 按模型能力选择 Tool Calling、结构化输出和流式策略，不假设所有 OpenAI-compatible 服务行为完全一致。
- [ ] 支持本地模型离线部署，明确最低上下文窗口、Tool Calling 能力和硬件要求。
- [ ] 评估按任务选择模型：简单查询使用低成本模型，复杂诊断和报告使用高能力模型。
- [ ] 评估 MCP 接入，仅暴露经过权限控制的只读查询能力，不允许模型访问任意文件和命令。
- [ ] 建立模型版本升级回归流程，同一评测集对比事实准确率、Tool 选择率、证据覆盖率、延迟和 Token 成本。

## 安全与运行管理

- [ ] 为远程部署增加用户认证和独立的密钥隔离。
- [ ] 增加请求频率和请求体大小限制。
- [ ] 非本地部署时增加模型服务地址白名单，防止任意外部请求。
- [ ] 根据用户设置对 IP、Payload 和 ARXML 敏感数据进行脱敏。
- [ ] 增加结构化审计日志，禁止记录 API Key 和原始敏感 Payload。
- [ ] 为多用户部署增加项目空间、会话隔离、配额和审计策略。

## 测试与质量

- [x] 使用固定链路测试十四个 Tool 的核心行为。
- [x] 使用真实 `test1.pcap` 校验订阅统计和时间线结果。
- [x] 使用模拟模型覆盖零次、一次、多次 Tool 调用、流式分片、上游失败和主动取消。
- [ ] 验证 DeepSeek、OpenAI、阿里云百炼和本地兼容接口。
- [ ] 测试前端空状态、加载状态、错误状态和解析会话切换。
