"""模型运行配置；实际调用统一由 LangChain 集成层完成。"""

from .config import ModelConfig, get_model_config

__all__ = [
    "ModelConfig",
    "get_model_config",
]
