"""运行时模型配置。

浏览器可以向本地分析进程提交密钥，但后端不会返回、记录或写入磁盘，
前端也不写入 localStorage。正式部署仍优先使用环境变量配置。
"""
from __future__ import annotations  # 开启Python3.7+的延迟注解，支持dataclass里前向引用

from dataclasses import dataclass
import os
from threading import Lock
from urllib.parse import urlparse

# DeepSeek 默认API地址
_DEFAULT_API_BASE = "https://api.deepseek.com"
# 默认调用模型
_DEFAULT_MODEL = "deepseek-v4-flash"


@dataclass(frozen=True)
class ModelConfig:
    """
    模型调用完整配置数据类，frozen=True 实例不可变，防止外部意外修改配置对象
    :param api_key: LLM API密钥
    :param api_base: API接口基础地址
    :param model: 模型名称
    :param timeout_seconds: 请求超时秒数
    :param source: 配置来源，可选 runtime / environment / none
    """
    api_key: str
    api_base: str
    model: str
    timeout_seconds: float
    source: str

    @property
    def configured(self) -> bool:
        """判断配置是否完整可用：key、接口地址、模型三者全部非空才算已配置"""
        return bool(self.api_key and self.api_base and self.model)


# 线程锁：多线程场景保护全局运行时变量读写，防止读写撕裂
_lock = Lock()
# 进程内存内保存的运行时配置，仅驻内存，不落地磁盘
_runtime_api_key = ""
_runtime_api_base = ""
_runtime_model = ""


def get_model_config() -> ModelConfig:
    """
    按运行时配置、环境变量、默认值的顺序解析模型配置。
    优先级：进程内存运行时配置(runtime) > 系统环境变量 > 代码内置默认值
    返回组装完成不可变ModelConfig对象
    """
    # 加锁读取全局运行时变量，多线程安全拷贝局部变量，减少锁持有时间
    with _lock:
        runtime_key = _runtime_api_key
        runtime_base = _runtime_api_base
        runtime_model = _runtime_model

    # 读取环境变量，优先 AI_API_KEY，其次 DEEPSEEK_API_KEY，去除首尾空白
    env_key = (
        os.getenv("AI_API_KEY", "").strip()
        or os.getenv("DEEPSEEK_API_KEY", "").strip()
    )

    # 判断配置来源
    # 1. runtime_key非空：来自接口动态设置（浏览器前端提交）
    # 2. runtime空但env_key存在：来自系统环境变量
    # 3. 两者都为空：无有效密钥
    source = "runtime" if runtime_key else ("environment" if env_key else "none")

    return ModelConfig(
        # 密钥优先级：内存运行时 > 环境变量
        api_key=runtime_key or env_key,
        # api_base优先级：内存运行时 > AI_API_BASE环境变量 > 内置默认地址；rstrip去除末尾多余/，避免拼接url双斜杠
        api_base=(runtime_base or os.getenv("AI_API_BASE", _DEFAULT_API_BASE)).rstrip("/"),
        # model优先级：内存运行时 > AI_MODEL环境变量 > 默认模型，strip清理首尾空格换行
        model=runtime_model or os.getenv("AI_MODEL", _DEFAULT_MODEL).strip(),
        timeout_seconds=_read_timeout(),
        source=source,
    )


def set_runtime_config(
    *,
    api_key: str | None,
    api_base: str,
    model: str,
) -> ModelConfig:
    """
    更新当前进程内凭据，**仅保存在内存，不写磁盘**，不向调用方返回完整密钥。
    仅关键字传参调用，必须指定api_key/api_base/model
    :param api_key: 新传入密钥，允许None；为空则复用当前已有的配置
    :param api_base: API接口地址，必填
    :param model: 模型名称，必填
    :raises ValueError: key为空、url非法、model为空抛出异常
    :return: 更新之后完整的配置对象（内部api_key字段仍然存在，但是对外接口public_config不会暴露）
    """
    # 获取当前现有配置，用于做值回退
    current = get_model_config()
    # 逻辑：传入api_key为空字符串/None，复用上一轮已经设置好的运行时key
    next_key = (api_key or "").strip() or current.api_key
    # 清理接口地址，去除首尾空白，去除末尾多余斜杠
    next_base = api_base.strip().rstrip("/")
    next_model = model.strip()

    # 参数校验：密钥不能为空
    if not next_key:
        raise ValueError("API Key 不能为空")
    # 参数校验：必须合法http/https地址
    if not _is_http_url(next_base):
        raise ValueError("API Base 必须是有效的 http(s) 地址")
    # 参数校验：模型名不能为空
    if not next_model:
        raise ValueError("模型名称不能为空")

    # 修改全局内存变量，加锁保证多线程并发修改安全
    global _runtime_api_key, _runtime_api_base, _runtime_model
    with _lock:
        _runtime_api_key = next_key
        _runtime_api_base = next_base
        _runtime_model = next_model
    # 修改完成，重新读取并返回配置
    return get_model_config()


def public_config(config: ModelConfig | None = None) -> dict[str, object]:
    """
    返回对外公开模型连接状态，**脱敏接口，绝对不返回API Key密钥**，用于返回给前端浏览器。
    :param config: 可选传入已经解析好的ModelConfig；不传就实时读取当前全局配置
    :return: 字典，包含是否配置完成、接口地址、模型名、配置来源，无密钥
    """
    resolved = config or get_model_config()
    return {
        "configured": resolved.configured,
        "api_base": resolved.api_base,
        "model": resolved.model,
        "source": resolved.source,
    }


def _is_http_url(value: str) -> bool:
    """
    私有辅助函数，校验字符串是否是合法http/https url
    urlparse拆分url，校验协议是http/https，并且存在域名netloc
    """
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _read_timeout() -> float:
    """
    私有辅助函数读取请求超时时间，从环境变量 AI_TIMEOUT_SECONDS读取
    做边界钳位：最小5秒，最大300秒，防止配置极端值；解析失败返回默认60秒
    :return: float 超时秒数
    """
    try:
        # max(min())实现数值钳位：限制区间 [5,300]
        return max(5.0, min(float(os.getenv("AI_TIMEOUT_SECONDS", "60")), 300.0))
    except ValueError:
        # 环境变量不是合法数字，捕获异常回退默认60s
        return 60.0
