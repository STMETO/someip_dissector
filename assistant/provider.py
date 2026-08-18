"""轻量的 OpenAI‑compatible Chat Completions 客户端。

第一版只使用 Python 标准库，避免 Tool 和 UI 绑定特定 AI SDK；后续可以替换
供应商适配层，而不改变现有 Tool 与页面接口。
"""
from __future__ import annotations  # 延迟类型注解，支持向前引用

import json
from typing import Any
# urllib 标准库网络异常类型
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

# 导入上一份代码的数据配置对象，包含api_key、api_base、超时、模型名等
from .config import ModelConfig


class ModelProviderError(RuntimeError):
    """允许安全显示给用户的模型连接错误。
    自定义业务异常：所有模型调用相关的业务错误全部抛出此异常，上层可以捕获并直接展示给前端UI，
    不会直接抛出底层原始网络异常，隔离底层实现细节。
    """


def create_chat_completion(
    config: ModelConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    调用兼容OpenAI协议的聊天补全接口，返回第一条choice内的message对象（包含content / tool_calls）
    完全使用标准库urllib，不依赖openai、deepseek第三方SDK。

    :param config: ModelConfig 对象，包含密钥、接口地址、模型、超时参数
    :param messages: 对话历史，OpenAI格式消息列表 [{"role":"user","content":"xxx"}, ...]
    :param tools: function‑call工具定义列表，OpenAI tools协议格式
    :return: dict，返回choices[0]["message"]，内含content、tool_calls等字段
    :raises ModelProviderError: 网络、超时、http错误、返回报文解析错误统一抛出该自定义异常
    """
    # 拼接完整请求地址，自动处理末尾斜杠
    endpoint = _chat_endpoint(config.api_base)

    # 组装OpenAI兼容请求体
    payload = {
        "model": config.model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",       # 自动模式：模型自行决定是否调用工具
        "temperature": 0.1,          # 低温度，偏向确定性输出，适合工具调用、解析协议类任务
    }

    # 针对DeepSeek官方接口特殊处理：V4版本默认开启思考模式，本业务不需要推理思考输出，强制关闭thinking
    # 判断hostname为api.deepseek.com才注入此字段；其他兼容OpenAI的第三方服务商不受影响
    if urlparse(config.api_base).hostname == "api.deepseek.com":
        payload["thinking"] = {"type": "disabled"}

    # 构造HTTP请求对象
    request = Request(
        endpoint,
        # ensure_ascii=False：中文不转义为\uXXXX，编码为utf‑8字节流
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {config.api_key}",  # Bearer鉴权头，OpenAI系列通用
            "Content-Type": "application/json",
            "Accept": "application/json",
            # HTTP Header 名称和值必须是 ASCII；不能使用排版用的不换行连字符。
            "User-Agent": "someip-dissector-assistant/1.0",
        },
    )

    try:
        # 发起http请求，超时取自配置内timeout_seconds
        with urlopen(request, timeout=config.timeout_seconds) as response:
            # 读取返回字节，utf8解码，解析json字典
            data = json.loads(response.read().decode("utf-8"))

    # HTTP状态码非200，例如401密钥错误、429限流、404地址错误、500服务内部错
    except HTTPError as exc:
        detail = _http_error_detail(exc)
        # 使用 raise ... from exc 保存原始异常堆栈，便于日志排查；对外抛出自定义异常
        raise ModelProviderError(f"模型服务返回 HTTP {exc.code}: {detail}") from exc
    # URLError：域名解析失败、网络不通、代理错误等底层连接问题
    except URLError as exc:
        raise ModelProviderError(f"无法连接模型服务: {exc.reason}") from exc
    # 请求超时异常
    except TimeoutError as exc:
        raise ModelProviderError("模型请求超时") from exc
    # urllib 在发送 Header 时才执行 ASCII 编码，API Key 或 Header 中出现
    # 非 ASCII 字符会在这里失败，统一转换成前端可读的业务错误。
    except UnicodeEncodeError as exc:
        raise ModelProviderError(
            "模型请求的 HTTP Header 包含非 ASCII 字符，请检查 API Key"
        ) from exc
    # 两种解析错误：返回内容不是utf8；返回不是合法JSON
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelProviderError("模型服务返回了无法解析的响应") from exc
    except (OSError, ValueError) as exc:
        raise ModelProviderError(f"模型请求构造或连接失败: {exc}") from exc

    # 校验返回报文结构，防止服务返回格式异常导致keyerror崩溃
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelProviderError("模型响应中缺少 choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ModelProviderError("模型响应中缺少 message")

    # 只返回message字典，上层业务直接读取content或者tool_calls
    return message


def _chat_endpoint(api_base: str) -> str:
    """
    私有辅助函数：自动拼接 /chat/completions 端点。
    兼容两种输入形式：
        1. 传入 https://api.deepseek.com  → https://api.deepseek.com/chat/completions
        2. 传入已经带后缀 https://xxx/v1/chat/completions → 直接原样返回
    """
    base = api_base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _http_error_detail(exc: HTTPError) -> str:
    """
    私有辅助函数：解析HTTPError的响应body，提取服务商返回的error message。
    很多时候401/429错误的详细信息放在response body里面，需要读取exc.read()获取。
    捕获全部异常，防止错误体本身不是json时二次崩溃。
    返回截断到600字符，避免返回超长错误文本传给前端。
    """
    try:
        body = json.loads(exc.read().decode("utf-8"))
        error = body.get("error", {})
        detail = error.get("message") if isinstance(error, dict) else error
        return str(detail or "请求失败")[:600]
    except Exception:
        # 解析失败，直接返回通用提示
        return "请求失败"
