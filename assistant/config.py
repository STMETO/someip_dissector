"""Runtime model configuration.

The browser may submit a key for this local analysis process, but the key is
never returned, logged, written to disk, or stored in browser localStorage.
Environment variables remain the preferred deployment configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from threading import Lock
from urllib.parse import urlparse

_DEFAULT_API_BASE = "https://api.deepseek.com"
_DEFAULT_MODEL = "deepseek-v4-flash"


@dataclass(frozen=True)
class ModelConfig:
    api_key: str
    api_base: str
    model: str
    timeout_seconds: float
    source: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_base and self.model)


_lock = Lock()
_runtime_api_key = ""
_runtime_api_base = ""
_runtime_model = ""


def get_model_config() -> ModelConfig:
    """Resolve runtime values first, then environment values and defaults."""
    with _lock:
        runtime_key = _runtime_api_key
        runtime_base = _runtime_api_base
        runtime_model = _runtime_model

    env_key = (
        os.getenv("AI_API_KEY", "").strip()
        or os.getenv("DEEPSEEK_API_KEY", "").strip()
    )
    source = "runtime" if runtime_key else ("environment" if env_key else "none")
    return ModelConfig(
        api_key=runtime_key or env_key,
        api_base=(runtime_base or os.getenv("AI_API_BASE", _DEFAULT_API_BASE)).rstrip("/"),
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
    """Update process-local credentials without exposing the resolved key."""
    current = get_model_config()
    next_key = (api_key or "").strip() or current.api_key
    next_base = api_base.strip().rstrip("/")
    next_model = model.strip()

    if not next_key:
        raise ValueError("API Key 不能为空")
    if not _is_http_url(next_base):
        raise ValueError("API Base 必须是有效的 http(s) 地址")
    if not next_model:
        raise ValueError("模型名称不能为空")

    global _runtime_api_key, _runtime_api_base, _runtime_model
    with _lock:
        _runtime_api_key = next_key
        _runtime_api_base = next_base
        _runtime_model = next_model
    return get_model_config()


def public_config(config: ModelConfig | None = None) -> dict[str, object]:
    """Return model status without returning any credential material."""
    resolved = config or get_model_config()
    return {
        "configured": resolved.configured,
        "api_base": resolved.api_base,
        "model": resolved.model,
        "source": resolved.source,
    }


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _read_timeout() -> float:
    try:
        return max(5.0, min(float(os.getenv("AI_TIMEOUT_SECONDS", "60")), 300.0))
    except ValueError:
        return 60.0
