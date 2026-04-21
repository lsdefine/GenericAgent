# ══════════════════════════════════════════════════════════════════════════════
#  aduAgent — config.py (Pydantic-Settings, Fail-fast, hot-reload)
#  Ground Truth: Kimi K2.6 via opencode.ai/zen/go
# ══════════════════════════════════════════════════════════════════════════════
"""
统一配置入口。环境变量优先级高于 .env 文件。
绝对禁止回退到 mykey.py。配错即崩溃 (Fail-fast)。
"""
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ADU_",
        extra="ignore",
    )

    # ── proxy ──
    proxy: str = "http://127.0.0.1:2082"

    # ── mixin_config ──
    mixin_llm_nos: list[str] = ["kimi-k2.6"]
    mixin_max_retries: int = 10
    mixin_base_delay: float = 0.5

    @property
    def mixin_config(self) -> dict:
        return {
            "llm_nos": self.mixin_llm_nos,
            "max_retries": self.mixin_max_retries,
            "base_delay": self.mixin_base_delay,
        }

    # ── native_oai_config_kimi (K2.6 via opencode.ai/zen/go) ──
    kimi_name: str = "kimi-k2.6"
    kimi_model: str = "kimi-k2.6"
    kimi_apibase: str = "https://opencode.ai/zen/go"
    kimi_apikey: SecretStr          # ← Fail-fast: 必填，缺失抛 ValidationError
    kimi_connect_timeout: int = 10
    kimi_read_timeout: int = 120
    kimi_max_retries: int = 3

    @property
    def native_oai_config_kimi(self) -> dict:
        return {
            "name": self.kimi_name,
            "apikey": self.kimi_apikey.get_secret_value(),  # 下游消费时解包
            "apibase": self.kimi_apibase,
            "model": self.kimi_model,
            "max_retries": self.kimi_max_retries,
            "connect_timeout": self.kimi_connect_timeout,
            "read_timeout": self.kimi_read_timeout,
        }


# 全局单例（按需热重载）
_settings: AgentSettings | None = None


def get_settings(force_reload: bool = False) -> AgentSettings:
    """获取配置单例；force_reload=True 时重新读取环境变量。"""
    global _settings
    if _settings is None or force_reload:
        _settings = AgentSettings()
    return _settings


# 兼容旧代码直接 import
settings = get_settings()
