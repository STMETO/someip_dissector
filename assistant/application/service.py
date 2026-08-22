"""AI 助手应用服务与进程内短期对话上下文。

本层只负责配置、上下文计划、会话持久化和 LangGraph 调用。意图分类、ReAct、Tool
路由、证据收集、Reflection 与回答发布全部由唯一生产 Graph 编排，不保留旧循环。
"""
from __future__ import annotations

import json
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
from ..conversation.store import (
    load_conversations,
    remove_conversations,
    save_conversations,
)
from ..answering.prompts import ANSWER_CONTRACT_VERSION, PROMPT_VERSION, render_system_prompt
from ..execution.run_record import AssistantRunRecord, log_run_record
# pydantic请求体模型，接收前端配置提交
from ..contracts.requests import AssistantConfigRequest
from ..conversation.context_budget import (
    ContextBudgetError,
    build_context_plan,
    tokenizer_name,
)
from ..tools import TOOL_DEFINITIONS
# 先加载 Graph 领域入口，再加载 LangChain 汇总包，保持初始化依赖方向稳定。
from .graph_runtime import AgentGraphExecutionError, run_agent_graph
from ..integrations.langchain import (
    ModelFactoryError,
    ModelRequestError,
    create_chat_model,
    create_tool_context,
    probe_chat_model,
    provider_catalog,
    resolve_chat_model_provider,
)
from ..integrations.langchain.events import GraphStreamCancelled


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
    provider_name = resolve_chat_model_provider(config)
    provider = next(
        item for item in provider_catalog() if item["provider"] == provider_name
    )
    result.update({
        "effective_provider": provider_name,
        "provider_label": provider["label"],
        "supports_tools": provider["supports_tools"],
        "supports_stream": provider["supports_stream"],
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
        result = probe_chat_model(config)
    except (ModelFactoryError, ModelRequestError) as exc:
        raise AssistantError(str(exc), 502) from exc
    return {
        **result,
        "provider": resolve_chat_model_provider(config),
        "model": config.model,
        "context_window": config.context_window,
    }


def _resolve_comparison_sessions(
    current_session_id: str,
    requested_session_ids: list[str],
) -> list[Any]:
    """把用户明确选择的记录解析为本轮只读白名单。"""
    if not isinstance(requested_session_ids, list):
        raise AssistantError("comparison_session_ids 必须是数组", 400)
    unique_ids: list[str] = []
    for value in requested_session_ids:
        session_id = str(value or "").strip()
        if not session_id or session_id == current_session_id or session_id in unique_ids:
            continue
        if len(session_id) > 128:
            raise AssistantError("比较会话 ID 长度不能超过 128 个字符", 400)
        unique_ids.append(session_id)
    if len(unique_ids) > 3:
        raise AssistantError("一次最多允许比较三个其他解析记录", 400)

    states = []
    for session_id in unique_ids:
        state = get_session(session_id)
        if state is None:
            raise AssistantError(f"比较会话不存在或已过期: {session_id}", 404)
        states.append(state)
    return states


def chat(
    session_id: str,
    question: str,
    conversation_id: str | None = None,
    progress: ProgressCallback | None = None,
    cancel_event: Event | None = None,
    request_id: str | None = None,
    comparison_session_ids: list[str] | None = None,
) -> dict[str, Any]:
    """
    用户聊天主入口函数。接收用户提问，执行完整 LangGraph，返回回答结果。
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
    comparison_states = _resolve_comparison_sessions(
        session_id,
        comparison_session_ids or [],
    )

    rid = request_id or uuid4().hex
    provider_name = resolve_chat_model_provider(config)
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
            comparison_states=comparison_states,
        )
        run_record.finish("completed")
        result["run"] = run_record.to_public_dict()
        _notify(progress, {
            "type": "completed",
            "request_id": rid,
            "graph_run_id": run_record.graph_run_id,
            "status": "completed",
        })
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
    comparison_states: list[Any],
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
                system_prompt=render_system_prompt(
                    state,
                    config,
                    provider_name,
                    [
                        {
                            "session_id": item.session_id,
                            "pcap_name": getattr(item, "pcap_name", ""),
                        }
                        for item in comparison_states
                    ],
                ),
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
        allowed_session_ids = {item.session_id for item in comparison_states}
        try:
            model = create_chat_model(config, require_tools=True)
            runtime_context = create_tool_context(
                session_id,
                run_record,
                allowed_session_ids=allowed_session_ids,
                model_config=config,
                cancel_event=cancel_event,
            )
            # build_context_plan 的首条 System Prompt 由 Graph 节点统一注入；较早
            # 对话摘要仍作为后续 SystemMessage 保留，避免重复注入主提示词。
            graph_messages = [
                item for index, item in enumerate(context.messages)
                if not (index == 0 and item.get("role") == "system")
            ]
            graph_result = run_agent_graph(
                model=model,
                system_prompt=str(context.messages[0]["content"]),
                messages=graph_messages,
                context=runtime_context,
                run_record=run_record,
                progress=progress,
                cancel_event=cancel_event,
            )
        except GraphStreamCancelled as exc:
            raise AssistantCancelled("请求已取消") from exc
        except ModelFactoryError as exc:
            raise AssistantError(str(exc), 400) from exc
        except ModelRequestError as exc:
            raise AssistantError(str(exc), 502) from exc
        except AgentGraphExecutionError as exc:
            if cancel_event is not None and cancel_event.is_set():
                raise AssistantCancelled("请求已取消") from exc
            raise AssistantError(str(exc), 502) from exc

        _check_cancel(cancel_event)
        answer = graph_result.answer
        used_tools = graph_result.tools

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
    comparison_session_ids: list[str] | None = None,
) -> Iterator[str]:
    """以 NDJSON 事件流输出工具进度和最终结果。

    LangGraph 同步流在单独线程执行；生成器每十秒输出一次 heartbeat，防止长时间
    模型请求被代理误判为空闲连接。同步 ``chat`` 接口继续保留兼容。
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
                comparison_session_ids,
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
