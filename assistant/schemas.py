"""AI 助手 API 的请求参数校验模型。

使用 Pydantic 定义HTTP接口接收的JSON请求体模型，
用于后端接收浏览器发来的POST请求，自动做参数校验、类型转换。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class AssistantConfigRequest(BaseModel):
    """
    更新模型运行配置的请求体模型。
    对应前端网页提交配置的接口，前端POST的JSON会映射到这个类。
    用来接收浏览器传过来 api_key、api_base、model，给后端 set_runtime_config 使用。

    注意：api_key允许传null，代表“不修改密钥，复用当前内存里已有的key”，只改接口地址或者模型。
    """
    # api_key可以不传/传null；最大长度4096，防止传入超长恶意字符串
    api_key: str | None = Field(default=None, max_length=4096)
    # api_base 必填，最短8字符（保证至少类似http://x），最大2048，限制URL长度
    api_base: str = Field(min_length=8, max_length=2048)
    # model 必填，模型名称，非空，限制长度
    model: str = Field(min_length=1, max_length=256)
    # Provider 只决定请求适配方式；auto 会根据 API 地址自动判断 DeepSeek。
    provider: str = Field(default="auto", min_length=1, max_length=64)
    # 该值必须以供应商文档为准，用于请求前的本地上下文预算保护。
    context_window: int = Field(default=65536, ge=4096, le=2_000_000)
    max_output_tokens: int = Field(default=4096, ge=256, le=131072)
    stream: bool = True


class AssistantChatRequest(BaseModel):
    """
    AI对话提问接口的请求体模型。
    用户在网页输入问题，点击发送，前端POST的JSON映射为此模型。
    """
    # 用户提问内容，不能为空，上限8000字符，防止超大输入压垮大模型
    question: str = Field(min_length=1, max_length=8000)
    # 会话ID，可选。用来区分不同对话；传null代表新建一次对话，不关联历史上下文
    conversation_id: str | None = Field(default=None, max_length=128)
    # 前端生成请求ID，用于显式取消仍在后台执行的模型请求。
    request_id: str | None = Field(default=None, min_length=8, max_length=128)


class AssistantPersistenceRequest(BaseModel):
    """设置当前解析记录是否将 AI 对话一起保存到磁盘。"""

    enabled: bool
