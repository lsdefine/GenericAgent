# ══════════════════════════════════════════════════════════════════════════════
#  aduAgent — config.py (Pydantic-Settings, Fail-fast, hot-reload)
#  Ground Truth: Kimi K2.6 via opencode.ai/zen/go
# ══════════════════════════════════════════════════════════════════════════════
"""
统一配置入口。环境变量优先级高于 .env 文件。
绝对禁止回退到 mykey.py。配错即崩溃 (Fail-fast)。
"""
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── env_file 锚定到本文件所在目录，不受调用方 cwd 漂移影响 (E3 根因修复) ──
_HERE = Path(__file__).resolve().parent
_ENV = _HERE / ".env"


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        # 存在则用绝对路径，不存在显式 None → 允许纯环境变量模式（未来迁 setx / CI secrets 无需改码）
        env_file=str(_ENV) if _ENV.exists() else None,
        env_file_encoding="utf-8",
        env_prefix="ADU_",
        extra="forbid",           # 拼错变量立即炸，不再静默吞掉 (纵深防御)
        case_sensitive=False,
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
    kimi_apikey: SecretStr = Field(..., description="Kimi K2.6 API key, required (ADU_KIMI_APIKEY)")
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


# ══════════════════════════════════════════════════════════════════════════════
#  全局单例 + Fail-fast 守门
#  - 配置错误 exit(78)  EX_CONFIG (sysexits.h) → CI/CD 可据此与代码异常(1)分流
#  - 运行时代码 bug 仍走正常异常路径
# ══════════════════════════════════════════════════════════════════════════════
@lru_cache(maxsize=1)
def get_settings() -> AgentSettings:
    """获取配置单例；ValidationError → exit(78) 并打印人类可读诊断。"""
    try:
        return AgentSettings()
    except ValidationError as e:
        missing = [".".join(str(x) for x in err["loc"]) for err in e.errors() if err["type"] == "missing"]
        extras  = [".".join(str(x) for x in err["loc"]) for err in e.errors() if err["type"] == "extra_forbidden"]
        sys.stderr.write("\n[CONFIG FATAL] AgentSettings validation failed:\n")
        if missing:
            sys.stderr.write(f"  missing required   : {missing}\n")
        if extras:
            sys.stderr.write(f"  unknown (forbidden): {extras}  ← typo? extra='forbid' is on\n")
        sys.stderr.write(f"  env_file expected  : {_ENV}  (exists={_ENV.exists()})\n")
        sys.stderr.write(f"  env_prefix required: ADU_  (e.g. ADU_KIMI_APIKEY=sk-xxx)\n")
        sys.stderr.write("  running from any cwd is fine now (abs path fix in place).\n\n")
        sys.exit(78)  # sysexits.h EX_CONFIG


# 兼容旧代码直接 import：模块级 settings 触发 fail-fast（配错即崩溃）
settings = get_settings()
