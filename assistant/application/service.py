"""AI 助手编排与进程内短期对话上下文。

本层是整个AI助手业务的核心编排层：
1. 维护内存里的对话会话历史（进程内，程序重启全部丢失）
2. 实现工具调用循环：AI → 调用本地工具 → 把工具结果丢回AI，多轮往复
3. 拼接System提示词、管理历史消息窗口、限制最大工具调用轮次
4. 对接上层HTTP接口，向下调用config配置模块、provider大模型客户端、tools工具执行模块
注意：对话默认只保存在内存；用户显式开启保存后才写入解析记录目录。
会话以 (session_id, conversation_id) 二元组隔离，API Key 和 Tool 原始结果不落盘。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Any, Callable, Iterator
from uuid import uuid4  # 生成唯一会话ID

# 项目内部模块：抓包分析session，每个浏览器标签对应一个session_id，持有pcap报文状态
from web.backend.handlers.analysis import get_session
from utils.logger import get_logger

# 导入前面写好的配置模块
from ..llm.config import get_model_config, public_config, set_runtime_config
# 导入大模型客户端，自定义异常
from ..llm.gateway import ModelProviderError, create_chat_completion, probe_model
from ..answering.navigation import validate_answer_navigation_links
from ..conversation.store import (
    load_conversations,
    remove_conversations,
    save_conversations,
)
from ..llm.providers import provider_catalog, resolve_provider
from ..answering.prompts import ANSWER_CONTRACT_VERSION, PROMPT_VERSION, render_system_prompt
from ..execution.run_record import AssistantRunRecord, log_run_record
# pydantic请求体模型，接收前端配置提交
from ..contracts.requests import AssistantConfigRequest
from ..conversation.context_budget import (
    ContextBudgetError,
    build_context_plan,
    estimate_request_tokens,
    tokenizer_name,
)
# Tool Schema 仍参与模型上下文预算，具体执行交由独立执行器治理。
from ..tools import TOOL_DEFINITIONS, execute_tool
from ..execution.tool_executor import ToolExecutionCancelled, ToolExecutor


logger = get_logger(__name__)

_history_lock = Lock()      # 多线程锁，保护全局对话字典_conversations并发读写
"""
对话存储字典：
key = (session_id, conversation_id)
    session_id：浏览器标签对应的抓包分析会话，一个pcap对应一个session
    conversation_id：同一个抓包会话下，可以开启多轮独立聊天
value = list[dict]，OpenAI格式消息历史，仅驻留内存
"""
@dataclass
class _ConversationState:
    """单段对话的内存状态；API Key 和 Tool 原始结果不在此保存。"""

    history: list[dict[str, str]] = field(default_factory=list)
    context_history: list[dict[str, str]] = field(default_factory=list)
    summary: str = ""
    updated_at: str = ""
    model: str = ""


_conversations: dict[tuple[str, str], _ConversationState] = {}
_loaded_sessions: set[str] = set()
_persistent_sessions: set[str] = set()
_conversation_locks: dict[tuple[str, str], Lock] = {}
_active_requests: dict[str, tuple[str, Event]] = {}
_active_requests_lock = Lock()
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


class AssistantCancelled(RuntimeError):
    """用户主动取消当前模型请求。"""


def status() -> dict[str, object]:
    """获取当前模型配置状态，对外脱敏接口，直接返回给前端。"""
    config = get_model_config()
    result = public_config(config)
    provider = resolve_provider(config)
    result.update({
        "effective_provider": provider.capabilities.provider,
        "provider_label": provider.capabilities.label,
        "supports_tools": provider.capabilities.supports_tools,
        "supports_stream": provider.capabilities.supports_stream,
        "tokenizer": tokenizer_name(config.model),
        "providers": provider_catalog(),
    })
    return result


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
            provider=request.provider,
            context_window=request.context_window,
            max_output_tokens=request.max_output_tokens,
            stream=request.stream,
        )
    except ValueError as exc:
        # 参数校验失败（key为空、url非法等）转为业务异常，400返回前端
        raise AssistantError(str(exc), 400) from exc
    return status()


def probe() -> dict[str, Any]:
    """验证当前模型的 Tool Calling 能力；该操作会产生一次最小模型请求。"""
    config = get_model_config()
    if not config.configured:
        raise AssistantError("请先配置模型 API Key", 503)
    try:
        result = probe_model(config)
    except ModelProviderError as exc:
        raise AssistantError(str(exc), 502) from exc
    return {
        **result,
        "provider": resolve_provider(config).capabilities.provider,
        "model": config.model,
        "context_window": config.context_window,
    }


def chat(
    session_id: str,
    question: str,
    conversation_id: str | None = None,
    progress: ProgressCallback | None = None,
    cancel_event: Event | None = None,
    request_id: str | None = None,
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

    rid = request_id or uuid4().hex
    provider_name = resolve_provider(config).capabilities.provider
    run_record = AssistantRunRecord(
        request_id=rid,
        session_id=session_id,
        model=config.model,
        prompt_version=PROMPT_VERSION,
        answer_contract_version=ANSWER_CONTRACT_VERSION,
    )
    try:
        result = _chat_with_run_record(
            state=state,
            config=config,
            provider_name=provider_name,
            session_id=session_id,
            question=question,
            conversation_id=conversation_id,
            progress=progress,
            cancel_event=cancel_event,
            run_record=run_record,
        )
        run_record.finish("completed")
        result["run"] = run_record.to_public_dict()
        return result
    except AssistantCancelled:
        run_record.finish("cancelled", "cancelled")
        raise
    except AssistantError as exc:
        run_record.finish("failed", f"http_{exc.status_code}")
        raise
    except Exception:
        run_record.finish("failed", "internal_error")
        raise
    finally:
        # 结构化日志只包含指标，不包含问题、答案、Prompt、Tool 结果或密钥。
        log_run_record(logger, run_record)


def _chat_with_run_record(
    *,
    state: Any,
    config: Any,
    provider_name: str,
    session_id: str,
    question: str,
    conversation_id: str | None,
    progress: ProgressCallback | None,
    cancel_event: Event | None,
    run_record: AssistantRunRecord,
) -> dict[str, Any]:
    """在已创建运行记录的上下文中完成一次问答。"""
    _ensure_session_conversations_loaded(state)
    cid = conversation_id or uuid4().hex
    key = (session_id, cid)
    with _history_lock:
        conversation = _conversations.setdefault(key, _ConversationState())
        chat_lock = _conversation_locks.setdefault(key, Lock())

    with chat_lock:
        _check_cancel(cancel_event)
        with _history_lock:
            history = list(conversation.context_history or conversation.history)
            summary = conversation.summary
        try:
            context = build_context_plan(
                system_prompt=render_system_prompt(state, config, provider_name),
                history=history,
                summary=summary,
                question=question.strip(),
                tools=TOOL_DEFINITIONS,
                model=config.model,
                context_window=config.context_window,
                max_output_tokens=config.max_output_tokens,
            )
        except ContextBudgetError as exc:
            raise AssistantError(str(exc), 400) from exc

        _notify(progress, {
            "type": "context",
            "estimated_input_tokens": context.estimated_input_tokens,
            "context_window": context.context_window,
            "dropped_messages": context.dropped_messages,
            "tokenizer": context.tokenizer,
            "message": "正在分析问题并选择查询工具",
        })
        used_tools: list[dict[str, Any]] = []
        executor = ToolExecutor(
            session_id,
            run_record,
            tool_handler=execute_tool,
            logger=logger,
        )
        try:
            answer, verified_links = _run_tool_loop(
                config,
                list(context.messages),
                used_tools,
                executor,
                run_record,
                progress,
                cancel_event,
            )
        except ToolExecutionCancelled as exc:
            raise AssistantCancelled("请求已取消") from exc
        except ModelProviderError as exc:
            if cancel_event is not None and cancel_event.is_set():
                raise AssistantCancelled("请求已取消") from exc
            raise AssistantError(str(exc), 502) from exc

        _check_cancel(cancel_event)
        answer, invalid_link_count = validate_answer_navigation_links(
            answer, verified_links
        )
        run_record.invalid_navigation_link_count = invalid_link_count
        answer, limit_notice_added = _ensure_query_limit_notice(answer, used_tools)
        if invalid_link_count or limit_notice_added:
            # 流式预览可能已经收到模型原文，重置后只展示校验后的最终答案。
            _notify(progress, {"type": "text_reset"})
            _notify(progress, {"type": "text_delta", "delta": answer})

        with _history_lock:
            next_turn = [
                {"role": "user", "content": question.strip()},
                {"role": "assistant", "content": answer},
            ]
            conversation.history = (conversation.history + next_turn)[-200:]
            conversation.context_history = context.retained_history + next_turn
            conversation.summary = context.summary
            conversation.updated_at = _utc_now()
            conversation.model = config.model
        _save_session_conversations_if_enabled(state)

    return {
        "conversation_id": cid,
        "answer": answer,
        "tools": used_tools,
        "model": config.model,
        "usage": dict(run_record.token_usage),
        "context": {
            "estimated_input_tokens": context.estimated_input_tokens,
            "context_window": context.context_window,
            "dropped_messages": context.dropped_messages,
            "tokenizer": context.tokenizer,
        },
    }


def chat_stream(
    session_id: str,
    question: str,
    conversation_id: str | None = None,
    request_id: str | None = None,
) -> Iterator[str]:
    """以 NDJSON 事件流输出工具进度和最终结果。

    模型客户端是同步实现，因此用单独线程执行；生成器每十秒输出一次 heartbeat，
    防止长时间模型请求被代理误判为空闲连接。同步 ``chat`` 接口继续保留兼容。
    """
    events: Queue[dict[str, Any] | None] = Queue()
    rid = request_id or uuid4().hex
    cancel_event = Event()
    with _active_requests_lock:
        previous = _active_requests.get(rid)
        if previous is not None:
            previous[1].set()
        _active_requests[rid] = (session_id, cancel_event)

    def run() -> None:
        try:
            result = chat(
                session_id,
                question,
                conversation_id,
                events.put,
                cancel_event,
                rid,
            )
            events.put({"type": "result", "result": result})
        except AssistantCancelled:
            events.put({"type": "cancelled", "message": "请求已取消"})
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
            with _active_requests_lock:
                current = _active_requests.get(rid)
                if current is not None and current[1] is cancel_event:
                    _active_requests.pop(rid, None)
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


def cancel_request(request_id: str, session_id: str | None = None) -> bool:
    """标记活动请求为取消；返回 False 表示请求已经结束或不存在。"""
    with _active_requests_lock:
        current = _active_requests.get(request_id)
    if current is None:
        return False
    active_session_id, event = current
    if session_id is not None and active_session_id != session_id:
        return False
    event.set()
    return True


def conversation_overview(session_id: str) -> dict[str, Any]:
    """返回当前解析记录最近一段对话及持久化状态。"""
    state = get_session(session_id)
    if state is None:
        raise AssistantError("解析会话不存在或已过期", 404)
    _ensure_session_conversations_loaded(state)
    with _history_lock:
        rows = [
            {
                "conversation_id": cid,
                "history": list(conversation.history),
                "updated_at": conversation.updated_at,
                "model": conversation.model,
            }
            for (sid, cid), conversation in _conversations.items()
            if sid == session_id
        ]
        enabled = session_id in _persistent_sessions
    rows.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return {
        "available": bool(getattr(state, "persistent", False)),
        "enabled": enabled,
        "conversation": rows[0] if rows else None,
    }


def set_conversation_persistence(session_id: str, enabled: bool) -> dict[str, Any]:
    """开启或关闭对话持久化，不改变解析记录自身的保存状态。"""
    state = get_session(session_id)
    if state is None:
        raise AssistantError("解析会话不存在或已过期", 404)
    _ensure_session_conversations_loaded(state)
    if enabled and not getattr(state, "persistent", False):
        raise AssistantError("请先持久化保存当前解析记录，再开启 AI 对话保存", 409)
    with _history_lock:
        if enabled:
            _persistent_sessions.add(session_id)
        else:
            _persistent_sessions.discard(session_id)
    if enabled:
        _save_session_conversations_if_enabled(state)
    else:
        remove_conversations(state.session_dir)
    return conversation_overview(session_id)


def remove_persisted_conversations(session_id: str) -> None:
    """解析记录取消持久化时同步移除 AI 对话文件。"""
    state = get_session(session_id)
    if state is None:
        return
    with _history_lock:
        _persistent_sessions.discard(session_id)
    remove_conversations(state.session_dir)


def clear_conversations(session_id: str, delete_persisted: bool = False) -> None:
    """释放某个解析记录的内存对话，可选同时删除磁盘对话。"""
    state = get_session(session_id) if delete_persisted else None
    with _active_requests_lock:
        active_request_ids = [
            request_id
            for request_id, (active_session_id, _) in _active_requests.items()
            if active_session_id == session_id
        ]
        active_events = [
            _active_requests.pop(request_id)[1]
            for request_id in active_request_ids
        ]
    for event in active_events:
        event.set()
    with _history_lock:
        for key in [key for key in _conversations if key[0] == session_id]:
            _conversations.pop(key, None)
            _conversation_locks.pop(key, None)
        _loaded_sessions.discard(session_id)
        _persistent_sessions.discard(session_id)
    if delete_persisted and state is not None:
        remove_conversations(state.session_dir)


def clear_all_conversations() -> None:
    """清空进程内全部对话上下文，用于重置、调试。"""
    with _active_requests_lock:
        active_events = [event for _, event in _active_requests.values()]
        _active_requests.clear()
    for event in active_events:
        event.set()
    with _history_lock:
        _conversations.clear()
        _conversation_locks.clear()
        _loaded_sessions.clear()
        _persistent_sessions.clear()


def _ensure_session_conversations_loaded(state: Any) -> None:
    """每个解析记录只从磁盘恢复一次对话，避免页面并发请求重复读取。"""
    session_id = state.session_id
    with _history_lock:
        if session_id in _loaded_sessions:
            return
        payload = load_conversations(state.session_dir)
        if payload:
            for row in payload.get("conversations", []):
                if not isinstance(row, dict):
                    continue
                cid = str(row.get("conversation_id") or "")[:128]
                if not cid:
                    continue
                history = _sanitize_history(row.get("history"))
                context_history = _sanitize_history(
                    row.get("context_history", history)
                )
                _conversations[(session_id, cid)] = _ConversationState(
                    history=history,
                    context_history=context_history,
                    summary=str(row.get("summary") or "")[:20000],
                    updated_at=str(row.get("updated_at") or ""),
                    model=str(row.get("model") or "")[:256],
                )
            _persistent_sessions.add(session_id)
        _loaded_sessions.add(session_id)


def _save_session_conversations_if_enabled(state: Any) -> None:
    """将当前解析记录的对话快照写盘；未启用时直接返回。"""
    with _history_lock:
        if state.session_id not in _persistent_sessions:
            return
        rows = [
            {
                "conversation_id": cid,
                "history": list(conversation.history),
                "context_history": list(conversation.context_history),
                "summary": conversation.summary,
                "updated_at": conversation.updated_at,
                "model": conversation.model,
            }
            for (sid, cid), conversation in _conversations.items()
            if sid == state.session_id
        ]
        # 同一解析记录最多保留最近 20 段对话，避免磁盘文件无限增长。
        rows.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        save_conversations(state.session_dir, rows[:20])


def _sanitize_history(value: Any) -> list[dict[str, str]]:
    """只恢复 user/assistant 文本，拒绝磁盘文件注入 system 或 tool 消息。"""
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
            continue
        result.append({
            "role": item["role"],
            "content": str(item.get("content") or "")[:50000],
        })
    return result[-200:]


def _run_tool_loop(
    config: Any,
    messages: list[dict[str, Any]],
    used_tools: list[dict[str, Any]],
    executor: ToolExecutor,
    run_record: AssistantRunRecord,
    progress: ProgressCallback | None = None,
    cancel_event: Event | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """
    【核心工具调用循环】
    多轮往复：调用大模型 → 如果AI要调用工具，本地执行工具，把tool结果塞回messages，再次请求大模型
    循环有最大轮次保护，避免AI无限调用工具死循环。
    :param config: 模型配置
    :param messages: 完整消息上下文，会在循环中不断追加assistant、tool消息
    :param used_tools: output参数，记录调用过的工具，回传给前端展示
    :param executor: 单次问答共享的 Tool 预算执行器
    :return: AI 最终文本和可验证的导航证据
    """
    verified_links: list[dict[str, Any]] = []
    # 最后一轮必须给模型机会整合 Tool 结果；持续调用 Tool 会被模型轮数预算终止。
    for _ in range(executor.budget.max_model_rounds):
        _check_cancel(cancel_event)
        run_record.model_rounds += 1
        round_input_tokens = estimate_request_tokens(
            messages,
            TOOL_DEFINITIONS,
            config.model,
        )
        if round_input_tokens + config.max_output_tokens + 256 > config.context_window:
            raise ModelProviderError(
                "Tool 返回结果使当前请求超过模型上下文窗口，请缩小查询范围或调高上下文配置"
            )
        # 每一轮模型请求可能先输出文本再决定调用 Tool，前端以 reset 区分轮次。
        _notify(progress, {"type": "text_reset"})
        emitted_text = False

        def on_text_delta(delta: str) -> None:
            nonlocal emitted_text
            _check_cancel(cancel_event)
            emitted_text = True
            _notify(progress, {"type": "text_delta", "delta": delta})

        model_message = create_chat_completion(
            config,
            messages,
            TOOL_DEFINITIONS,
            on_text_delta=on_text_delta,
            cancel_event=cancel_event,
        )
        run_record.add_usage(model_message.get("_usage"))
        tool_calls = model_message.get("tool_calls") or []

        # 没有工具调用，直接拿到最终回答，退出循环返回文本
        if not tool_calls:
            content = _message_content(model_message.get("content"))
            if content:
                # 关闭流式或兼容接口没有增量时，仍通过统一事件显示完整回答。
                if not emitted_text:
                    _notify(progress, {"type": "text_delta", "delta": content})
                return content, verified_links
            raise ModelProviderError("模型没有返回可显示的回答")

        # Tool Calling 轮次产生的临时文本不属于最终回答，立即清空预览。
        _notify(progress, {"type": "text_reset"})

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
            raw_arguments = function.get("arguments")
            # 进度事件只展示可安全解析的参数预览；严格校验由 ToolExecutor 统一完成。
            arguments = _argument_preview(raw_arguments)
            _notify(progress, {
                "type": "tool_start",
                "name": name,
                "arguments": arguments,
                "message": _TOOL_PROGRESS_LABELS.get(name, f"正在调用 {name}"),
            })
            outcome = executor.execute(name, raw_arguments, cancel_event)
            _check_cancel(cancel_event)
            # 记录本次调用的工具，用于前端展示
            tool_record = {
                "name": name,
                "arguments": outcome.arguments,
                "links": outcome.links,
                "status": outcome.status,
                "ok": outcome.ok,
                "error_code": outcome.error_code,
                "duration_ms": outcome.duration_ms,
                "result_bytes": outcome.result_bytes,
            }
            used_tools.append(tool_record)
            verified_links.extend(outcome.verified_links)
            if outcome.status == "success":
                completion_label = "完成"
            elif outcome.status == "partial":
                completion_label = "部分完成"
            else:
                completion_label = "失败"
            _notify(progress, {
                "type": "tool_end",
                "name": name,
                "arguments": outcome.arguments,
                "ok": outcome.ok,
                "status": outcome.status,
                "error_code": outcome.error_code,
                "duration_ms": outcome.duration_ms,
                "message": (
                    f"{_TOOL_PROGRESS_LABELS.get(name, name).removeprefix('正在')}"
                    f"{completion_label}"
                ),
            })
            # 将工具执行结果组装tool角色消息，追加到messages，下一轮传给大模型
            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "name": name,
                "content": outcome.content,
            })

    # 循环耗尽最大次数，抛出异常
    raise ModelProviderError(
        f"模型连续 {executor.budget.max_model_rounds} 轮调用 Tool，已停止以避免循环"
    )


def _check_cancel(cancel_event: Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AssistantCancelled("请求已取消")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _argument_preview(value: Any) -> dict[str, Any]:
    """
    兼容解析AI输出的tool调用参数。
    部分LLM返回arguments是json字符串，部分直接返回dict，统一输出字典。
    解析失败仅返回空预览，ToolExecutor 仍会把它判定为参数错误。
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


def _ensure_query_limit_notice(
    answer: str,
    used_tools: list[dict[str, Any]],
) -> tuple[str, bool]:
    """部分查询失败时补充确定性的限制说明，避免模型掩盖缺失证据。"""
    incomplete = [item for item in used_tools if item.get("status") != "success"]
    if not incomplete or re.search(r"(?m)^#{1,6}\s*查询限制\s*$", answer):
        return answer, False
    lines = ["### 查询限制"]
    for item in incomplete:
        name = str(item.get("name") or "unknown_tool")
        code = str(item.get("error_code") or "partial_result")
        lines.append(f"- `{name}` 未完整完成（`{code}`），相关结论仅基于已返回证据。")
    return answer.rstrip() + "\n\n" + "\n".join(lines), True


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
