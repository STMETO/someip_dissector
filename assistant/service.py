"""AI 助手编排与进程内短期对话上下文。

本层是整个AI助手业务的核心编排层：
1. 维护内存里的对话会话历史（进程内，程序重启全部丢失）
2. 实现工具调用循环：AI → 调用本地工具 → 把工具结果丢回AI，多轮往复
3. 拼接System提示词、管理历史消息窗口、限制最大工具调用轮次
4. 对接上层HTTP接口，向下调用config配置模块、provider大模型客户端、tools工具执行模块
注意：所有对话只保存在内存，不落地磁盘；会话以(session_id, conversation_id)二元组做key隔离。
"""
from __future__ import annotations

import json
import logging
from queue import Empty, Queue
from threading import Lock, Thread
from typing import Any, Callable, Iterator
from uuid import uuid4  # 生成唯一会话ID

# 项目内部模块：抓包分析session，每个浏览器标签对应一个session_id，持有pcap报文状态
from web.backend.handlers.analysis import get_session

# 导入前面写好的配置模块
from .config import get_model_config, public_config, set_runtime_config
# 导入大模型客户端，自定义异常
from .provider import ModelProviderError, create_chat_completion
from .navigation import collect_navigation_links
# pydantic请求体模型，接收前端配置提交
from .schemas import AssistantConfigRequest
# 工具定义列表、执行工具函数、工具结果序列化
from .tools import TOOL_DEFINITIONS, execute_tool, tool_result_json


_MAX_TOOL_ROUNDS = 4        # 单次用户提问，最多允许AI执行工具调用循环轮数，防止无限循环
_MAX_HISTORY_MESSAGES = 12  # 内存中每个对话最多保留多少条历史消息，防止上下文无限膨胀占用token
logger = logging.getLogger(__name__)

_history_lock = Lock()      # 多线程锁，保护全局对话字典_conversations并发读写
"""
对话存储字典：
key = (session_id, conversation_id)
    session_id：浏览器标签对应的抓包分析会话，一个pcap对应一个session
    conversation_id：同一个抓包会话下，可以开启多轮独立聊天
value = list[dict]，OpenAI格式消息历史，仅驻留内存
"""
_conversations: dict[tuple[str, str], list[dict[str, str]]] = {}
ProgressCallback = Callable[[dict[str, Any]], None]

_TOOL_PROGRESS_LABELS = {
    "get_subscription_status": "正在查询订阅诊断总览",
    "find_service": "正在查找服务",
    "get_offer_timeline": "正在查询 Offer 时间线",
    "get_subscription_timeline": "正在查询订阅时间线",
    "search_messages": "正在检索报文",
    "get_message_detail": "正在读取报文详情",
    "get_notification_statistics": "正在统计 Notification",
    "get_payload_field": "正在读取 Payload 字段",
}


class AssistantError(RuntimeError):
    """
    AI助手业务自定义异常。
    封装业务错误信息 + HTTP状态码，上层接口捕获后直接返回给前端网页。
    """
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def status() -> dict[str, object]:
    """获取当前模型配置状态，对外脱敏接口，直接返回给前端。"""
    return public_config()


def configure(request: AssistantConfigRequest) -> dict[str, object]:
    """
    处理前端提交大模型配置接口。
    :param request: pydantic解析后的入参对象
    :return: 脱敏后的配置字典
    """
    try:
        # 调用config模块更新进程内存运行时配置
        config = set_runtime_config(
            api_key=request.api_key,
            api_base=request.api_base,
            model=request.model,
        )
    except ValueError as exc:
        # 参数校验失败（key为空、url非法等）转为业务异常，400返回前端
        raise AssistantError(str(exc), 400) from exc
    return public_config(config)


def chat(
    session_id: str,
    question: str,
    conversation_id: str | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """
    用户聊天主入口函数。接收用户提问，执行完整对话+工具调用循环，返回回答结果。
    :param session_id: 抓包分析会话ID，绑定打开的pcap抓包文件
    :param question: 用户输入的自然语言提问
    :param conversation_id: 可选，对话ID；None代表新建对话
    :return: 返回字典包含conversation_id、AI回答、本次调用过的工具列表、使用的模型名
    """
    # 根据session_id拿到抓包会话；会话过期/不存在抛出404
    state = get_session(session_id)
    if state is None:
        raise AssistantError("解析会话不存在或已过期", 404)

    # 获取当前全局大模型配置
    config = get_model_config()
    if not config.configured:
        # 没有配置api_key，返回503提示用户先配置
        raise AssistantError("请先配置模型 API Key", 503)

    # 没有传入对话id，则生成全新uuid作为本次对话标识
    cid = conversation_id or uuid4().hex
    # 二元key：同一个pcap(session_id)可以跑多个独立聊天(conversation_id)，互相隔离上下文
    key = (session_id, cid)

    # 加锁读取历史，拷贝副本，减少锁持有时间
    with _history_lock:
        history = list(_conversations.get(key, []))

    # 组装完整消息：system提示词 + 历史对话 + 用户最新提问
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(state, config)},
        *history,
        {"role": "user", "content": question.strip()},
    ]
    used_tools: list[dict[str, Any]] = []  # 记录本轮问答AI实际调用了哪些工具，返回给前端展示
    _notify(progress, {
        "type": "status",
        "stage": "model",
        "message": "正在分析问题并选择查询工具",
    })

    try:
        # 执行工具调用循环，拿到AI最终文本回答
        answer = _run_tool_loop(
            config,
            messages,
            session_id,
            used_tools,
            progress,
        )
    except ModelProviderError as exc:
        # 捕获底层大模型客户端异常，封装为业务异常，502代表上游模型服务出错
        raise AssistantError(str(exc), 502) from exc

    # 更新内存中的对话历史；做窗口截断，只保留最近_MAX_HISTORY_MESSAGES条，防止上下文无限变长
    with _history_lock:
        next_history = history + [
            {"role": "user", "content": question.strip()},
            {"role": "assistant", "content": answer},
        ]
        _conversations[key] = next_history[-_MAX_HISTORY_MESSAGES:]

    return {
        "conversation_id": cid,
        "answer": answer,
        "tools": used_tools,
        "model": config.model,
    }


def chat_stream(
    session_id: str,
    question: str,
    conversation_id: str | None = None,
) -> Iterator[str]:
    """以 NDJSON 事件流输出工具进度和最终结果。

    模型客户端是同步实现，因此用单独线程执行；生成器每十秒输出一次 heartbeat，
    防止长时间模型请求被代理误判为空闲连接。同步 ``chat`` 接口继续保留兼容。
    """
    events: Queue[dict[str, Any] | None] = Queue()

    def run() -> None:
        try:
            result = chat(session_id, question, conversation_id, events.put)
            events.put({"type": "result", "result": result})
        except AssistantError as exc:
            events.put({
                "type": "error",
                "message": str(exc),
                "status_code": exc.status_code,
            })
        except Exception:
            # 不把未知堆栈和敏感配置发送到浏览器，详细异常仍由服务端日志记录。
            logger.exception("AI 助手流式请求发生未处理异常")
            events.put({
                "type": "error",
                "message": "AI 助手处理请求时发生内部错误",
                "status_code": 500,
            })
        finally:
            events.put(None)

    Thread(target=run, name="assistant-chat-stream", daemon=True).start()
    while True:
        try:
            event = events.get(timeout=10.0)
        except Empty:
            yield json.dumps({"type": "heartbeat"}, ensure_ascii=False) + "\n"
            continue
        if event is None:
            break
        yield json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"


def clear_conversations(session_id: str) -> None:
    """清空某一个抓包session下全部的聊天对话。关闭pcap文件时调用，释放内存。"""
    with _history_lock:
        # 筛选所有key中session_id匹配的对话，全部删除
        for key in [key for key in _conversations if key[0] == session_id]:
            _conversations.pop(key, None)


def clear_all_conversations() -> None:
    """清空进程内全部对话上下文，用于重置、调试。"""
    with _history_lock:
        _conversations.clear()


def _run_tool_loop(
    config: Any,
    messages: list[dict[str, Any]],
    session_id: str,
    used_tools: list[dict[str, Any]],
    progress: ProgressCallback | None = None,
) -> str:
    """
    【核心工具调用循环】
    多轮往复：调用大模型 → 如果AI要调用工具，本地执行工具，把tool结果塞回messages，再次请求大模型
    循环有最大轮次保护，避免AI无限调用工具死循环。
    :param config: 模型配置
    :param messages: 完整消息上下文，会在循环中不断追加assistant、tool消息
    :param session_id: 抓包会话id，传给execute_tool，让工具读取pcap报文
    :param used_tools: output参数，记录调用过的工具，回传给前端展示
    :return str: AI最终输出给用户的文本答案
    """
    # 循环上限：最多跑 _MAX_TOOL_ROUNDS+1 次大模型请求，防止死循环
    for _ in range(_MAX_TOOL_ROUNDS + 1):
        # 请求大模型，传入全部上下文 + 全部工具定义
        model_message = create_chat_completion(config, messages, TOOL_DEFINITIONS)
        tool_calls = model_message.get("tool_calls") or []

        # 没有工具调用，直接拿到最终回答，退出循环返回文本
        if not tool_calls:
            content = _message_content(model_message.get("content"))
            if content:
                return content
            raise ModelProviderError("模型没有返回可显示的回答")

        # AI返回要调用工具，组装assistant消息，追加进上下文
        assistant_message = {
            "role": "assistant",
            "content": model_message.get("content") or "",
            "tool_calls": tool_calls,
        }
        # 兼容DeepSeek reasoning_content思考字段；虽然我们默认关闭思考，但做防御兼容返回
        if model_message.get("reasoning_content") is not None:
            assistant_message["reasoning_content"] = model_message["reasoning_content"]
        messages.append(assistant_message)

        # 遍历每一个工具调用，本地执行工具
        for call in tool_calls:
            call_id = str(call.get("id") or uuid4().hex)
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            # AI输出的arguments有可能是字符串，做兼容解析为字典
            arguments = _parse_arguments(function.get("arguments"))
            _notify(progress, {
                "type": "tool_start",
                "name": name,
                "arguments": arguments,
                "message": _TOOL_PROGRESS_LABELS.get(name, f"正在调用 {name}"),
            })
            try:
                # 在本地执行工具：查询pcap报文、查询服务、时间线等
                result = execute_tool(name, arguments, session_id)
            except Exception as exc:
                # 工具执行报错，错误信息作为工具返回结果传给大模型，AI可以感知工具失败
                result = {"error": str(exc)}
            tool_ok = "error" not in result
            # 记录本次调用的工具，用于前端展示
            tool_record = {
                "name": name,
                "arguments": arguments,
                "links": collect_navigation_links(name, arguments, result),
            }
            used_tools.append(tool_record)
            _notify(progress, {
                "type": "tool_end",
                "name": name,
                "arguments": arguments,
                "ok": tool_ok,
                "message": (
                    f"{_TOOL_PROGRESS_LABELS.get(name, name).removeprefix('正在')}"
                    f"{'完成' if tool_ok else '失败'}"
                ),
            })
            # 将工具执行结果组装tool角色消息，追加到messages，下一轮传给大模型
            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "name": name,
                "content": tool_result_json(result),
            })

    # 循环耗尽最大次数，抛出异常
    raise ModelProviderError("工具调用次数超过限制")


def _notify(
    progress: ProgressCallback | None,
    event: dict[str, Any],
) -> None:
    """进度回调失败不能中断模型与 Tool 主流程。"""
    if progress is None:
        return
    try:
        progress(event)
    except Exception:
        return


def _system_prompt(state: Any, config: Any) -> str:
    """
    生成System系统提示词。
    把当前pcap文件名、报文总数、当前模型、api地址注入prompt，同时约束AI的行为规则。
    强制AI不能瞎编数据，必须调用工具拿抓包事实，输出要带上报文索引证据。
    """
    return f"""你是 SOME/IP 和 SOME/IP‑SD 抓包分析助手。
当前解析会话包含 {state.total_messages} 条报文，PCAP 文件为 {state.pcap_name}。
当前实际调用的模型配置是 {config.model}，API 地址是 {config.api_base}。

规则：
1. 涉及服务、报文、Offer、Subscribe、Ack、Nack、Notification 或订阅异常的事实时，必须调用工具查询。
2. 工具结果是事实来源，不得虚构抓包中不存在的服务、客户端、数量或状态。
3. 明确区分事实与推断。信息不足时直接说明限制。
4. Service ID 同时显示十六进制形式。回答使用用户提问的语言。
5. 每个主要诊断结论必须至少引用一条工具证据，写明 message_index、frame_index 和 timestamp_iso；不能只写“来自工具”。
6. 用户询问模型身份时，只能回答上述实际模型名称与 API 配置，不得猜测未提供的版本或供应商信息。
7. 可用能力包括订阅总览、服务查找、Offer 时间线、订阅时间线、报文检索、单报文详情、Notification 统计和按路径读取 Payload 字段。
8. Tool 返回的关联规则属于项目诊断规则；不能把关联结果描述成协议线上直接携带的字段。
9. Offer 冲突必须以相同 Service ID 和 Instance ID 被多个 ECU 发布为准，不能仅因同一 Service ID 存在多个 Instance 而判冲突。
10. “已订阅但抓包内无 Notification”只是抓包时段内的现象，不等于已证明服务故障；观察到少量 Notification 也不能单独证明频率和业务行为完全健康。
11. 分析深层 Payload 时优先调用 get_payload_field；只有用户明确要求整条报文结构时才调用 get_message_detail 并返回解析树。
12. 回答中的可定位对象必须使用以下 Markdown 链接格式，不要只输出纯文本 ID：
    - 报文证据：`[Message 123 / Frame 456](#someip-message-123)`
    - 服务：`[Service 0x0A01](#someip-service-0x0A01)`
    - EventGroup：`[EventGroup 0xA005](#someip-eventgroup-0x0A01-0xA005)`
    - 信号时序：`[Open signal timing](#someip-signal?service=0x0A01&event=0xA005&start=1.0&end=2.0)`
    链接参数必须来自 Tool 结果或本次 Tool 参数，不能自行猜测。"""


def _parse_arguments(value: Any) -> dict[str, Any]:
    """
    兼容解析AI输出的tool调用参数。
    部分LLM返回arguments是json字符串，部分直接返回dict，统一输出字典。
    解析失败返回空字典，防止程序崩溃。
    """
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _message_content(content: Any) -> str:
    """
    兼容不同模型输出content格式：
    1.普通字符串；
    2.多模态数组格式 [{"type":"text","text":"xxx"}]
    提取文本内容，做清理。
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return "\n".join(part for part in parts if part).strip()
    return ""
