# AI 分析助手待办事项

## 第一版已完成

- [x] 在 Vue 页面中加入绑定解析会话的 AI 侧边对话框。
- [x] 支持配置 OpenAI-compatible API 地址、API Key 和模型名称。
- [x] 页面提交的 API Key 只保存在后端进程内存中。
- [x] 实现有调用次数限制的 Tool Calling 循环和服务端白名单分发。
- [x] 实现 `get_subscription_status`，查询 Offer、Subscribe、Ack 和 Notification 状态。
- [x] 按解析会话隔离并保存短期对话上下文。
- [x] 将每个 Tool 拆分到 `assistant/tools/` 下的独立文件。

## 下一阶段优先事项

- [ ] 抽取页面 API 和 AI Tool 共用的统一查询层。
- [ ] 新增 `find_service`，支持通过 ARXML 名称或 ID 查找服务。
- [ ] 新增 `get_offer_timeline`，提供时间戳、TTL 和状态变化。
- [ ] 新增 `search_messages`，支持按服务、方法、报文类型、IP 和时间过滤。
- [ ] 新增 `get_message_detail`，用于解释协议树和 Payload。
- [ ] 新增 `get_notification_statistics` 和信号字段统计工具。
- [ ] 在回答中返回包含报文序号、帧序号和时间戳的可验证证据。
- [ ] 支持点击 AI 证据跳转消息列表、订阅诊断和信号时序页面。

## 对话与模型接入

- [ ] 将基础请求客户端扩展成可插拔的模型供应商适配器。
- [ ] 使用 SSE 流式输出模型文本和 Tool 执行进度。
- [ ] 检查模型是否支持 Tool Calling 和所需上下文长度。
- [ ] 使用模型 Tokenizer 实现准确的上下文预算管理。
- [ ] 为长对话增加滚动摘要。
- [ ] 允许持久化解析记录选择是否同时保存 AI 对话。
- [ ] 增加取消请求和失败重试功能。

## 安全与运行管理

- [ ] 为远程部署增加用户认证和独立的密钥隔离。
- [ ] 增加请求频率、请求体大小、Tool 耗时和调用次数限制。
- [ ] 非本地部署时增加模型服务地址白名单，防止任意外部请求。
- [ ] 根据用户设置对 IP、Payload 和 ARXML 敏感数据进行脱敏。
- [ ] 记录模型耗时、Token 用量、Tool 耗时和错误指标。
- [ ] 增加结构化审计日志，禁止记录 API Key 和原始敏感 Payload。

## 测试与质量

- [ ] 为 Tool Schema、参数校验和白名单分发增加单元测试。
- [ ] 使用模拟模型测试零次、一次和多次 Tool 调用。
- [ ] 建立 Offer 和订阅问题的固定评测集。
- [ ] 验证 DeepSeek、OpenAI、阿里云百炼和本地兼容接口。
- [ ] 测试前端空状态、加载状态、错误状态和解析会话切换。
