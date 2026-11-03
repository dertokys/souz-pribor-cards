import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class ConfigError(ValueError):
    pass


def _number(name: str, default: str, cast):
    raw = os.getenv(name, default).strip()
    try:
        return cast(raw)
    except ValueError:
        raise ConfigError(f"{name}: ожидается число, получено «{raw}» — исправьте .env") from None


def _optional_float(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    return _number(name, "", float) if raw else None


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str | None
    model: str
    temperature: float | None
    structured_outputs: bool
    timeout: float
    max_attempts: int
    max_tokens: int
    reasoning_effort: str | None


def get_settings() -> Settings:
    return Settings(
        api_key=os.getenv("LLM_API_KEY", "").strip(),
        base_url=os.getenv("LLM_BASE_URL", "").strip() or None,
        model=os.getenv("LLM_MODEL", "openai/gpt-5-mini").strip(),
        temperature=_optional_float("LLM_TEMPERATURE"),
        structured_outputs=os.getenv("LLM_STRUCTURED_OUTPUTS", "true").lower() in {"1", "true", "yes"},
        timeout=_number("LLM_TIMEOUT", "120", float),
        max_attempts=max(1, _number("LLM_MAX_ATTEMPTS", "2", int)),
        max_tokens=_number("LLM_MAX_TOKENS", "16000", int),
        reasoning_effort=os.getenv("LLM_REASONING_EFFORT", "low").strip() or None,
    )
