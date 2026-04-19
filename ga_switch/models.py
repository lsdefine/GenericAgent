from dataclasses import dataclass, field
from typing import Any


PROVIDER_BACKEND_KINDS = (
    "native_claude",
    "native_oai",
    "claude_text",
    "oai_text",
)

ROUTE_KINDS = ("single", "failover")


def is_native_backend_kind(kind: str) -> bool:
    return str(kind or "").startswith("native_")


def backend_family(kind: str) -> str:
    kind = str(kind or "")
    if "claude" in kind:
        return "claude"
    return "oai"


@dataclass
class ProviderModel:
    id: int | None = None
    name: str = ""
    backend_kind: str = "oai_text"
    apikey: str = ""
    apibase: str = ""
    model: str = ""
    api_mode: str = "chat_completions"
    temperature: float = 1.0
    max_tokens: int = 8192
    context_win: int = 24000
    proxy: str | None = None
    timeout: int = 5
    read_timeout: int = 30
    max_retries: int = 1
    reasoning_effort: str | None = None
    thinking_type: str | None = None
    thinking_budget_tokens: int | None = None
    stream: bool = True
    is_enabled: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class RouteModel:
    id: int | None = None
    name: str = ""
    kind: str = "single"
    provider_id: int | None = None
    member_provider_ids: list[int] = field(default_factory=list)
    is_enabled: bool = True
    is_default: bool = False
    config: dict[str, Any] = field(default_factory=dict)
