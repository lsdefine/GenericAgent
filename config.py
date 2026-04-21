# ══════════════════════════════════════════════════════════════════════════════
#  aduAgent — config.py (Pydantic-Settings, Fail-fast, hot-reload)
# ══════════════════════════════════════════════════════════════════════════════
"""
统一配置入口。环境变量优先级高于 .env 文件。
绝对禁止回退到 mykey.py。配错即崩溃 (Fail-fast)。
"""
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
    mixin_base_delay: float = 5.0
    mixin_llm_nos: str = "gpt-4o"
    mixin_max_retries: int = 3

    @property
    def mixin_config(self) -> dict:
        return {
            "base_delay": self.mixin_base_delay,
            "llm_nos": self.mixin_llm_nos,
            "max_retries": self.mixin_max_retries,
        }

    # ── native_oai_config_kimi ──
    # **不设默认值** —— 缺失时 pydantic 直接抛出 ValidationError (Fail-fast)
    kimi_name: str = "kimi"
    kimi_model: str = "gpt-4o"
    kimi_apibase: str = "https://api.moonshot.cn/v1"
    kimi_apikey: str          # ← Fail-fast: 必填
    kimi_connect_timeout: int = 10
    kimi_read_timeout: int = 180
    kimi_max_retries: int = 3

    @property
    def native_oai_config_kimi(self) -> dict:
        return {
            "name": self.kimi_name,
            "model": self.kimi_model,
            "apibase": self.kimi_apibase,
            "apikey": self.kimi_apikey,
            "connect_timeout": self.kimi_connect_timeout,
            "read_timeout": self.kimi_read_timeout,
            "max_retries": self.kimi_max_retries,
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
