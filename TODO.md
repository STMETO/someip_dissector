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

- [x] 将页面 API 与 AI Tool 的共用查询逻辑抽取到 `analysis/queries/`。
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

- [x] 将基础请求客户端扩展为 `providers/` 可插拔适配层，支持 DeepSeek 和通用 OpenAI-compatible 接口。
- [x] 通过 NDJSON 实时输出模型文本、Tool 执行进度、Token 预算和最终结果。
- [x] 增加模型能力探测，验证 Tool Calling 与流式输出；上下文窗口由配置约束并在请求前校验。
- [x] 增加可插拔 Token 计数器；安装 `tiktoken` 时使用真实编码器，否则使用保守 Unicode 估算。
- [x] 为长对话增加有界滚动摘要，并将模型上下文历史与 UI 展示历史分离。
- [x] 允许持久化解析记录选择是否同时保存 AI 对话，API Key 和 Tool 原始结果不落盘。
- [x] 增加请求取消和失败问题重试功能。
- [ ] 为 DeepSeek、百炼和本地模型接入各供应商官方 Tokenizer，替代通用估算。

## 安全与运行管理

- [ ] 为远程部署增加用户认证和独立的密钥隔离。
- [ ] 增加请求频率、请求体大小、Tool 耗时和调用次数限制。
- [ ] 非本地部署时增加模型服务地址白名单，防止任意外部请求。
- [ ] 根据用户设置对 IP、Payload 和 ARXML 敏感数据进行脱敏。
- [ ] 记录模型耗时、Token 用量、Tool 耗时和错误指标。
- [ ] 增加结构化审计日志，禁止记录 API Key 和原始敏感 Payload。

## 测试与质量

- [x] 使用固定链路测试八个 Tool 的核心行为。
- [x] 使用真实 `test1.pcap` 校验订阅统计和时间线结果。
- [x] 使用模拟模型覆盖零次、一次、多次 Tool 调用、流式分片、上游失败和主动取消。
- [ ] 建立 Offer 和订阅问题的固定评测集。
- [ ] 验证 DeepSeek、OpenAI、阿里云百炼和本地兼容接口。
- [ ] 测试前端空状态、加载状态、错误状态和解析会话切换。
