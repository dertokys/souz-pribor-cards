import os
from dataclasses import dataclass

from dotenv import dotenv_values, find_dotenv


class ConfigError(ValueError):
    pass


def _env() -> dict[str, str]:
    values = {k: v for k, v in dotenv_values(find_dotenv()).items() if v is not None}
    values.update(os.environ)
    return values


def _number(env: dict[str, str], name: str, default: str, cast):
    raw = env.get(name, default).strip()
    try:
        return cast(raw)
    except ValueError:
        raise ConfigError(f"{name}: ожидается число, получено «{raw}» — исправьте .env") from None


def _optional_float(env: dict[str, str], name: str) -> float | None:
    raw = env.get(name, "").strip()
    return _number(env, name, "", float) if raw else None


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
    env = _env()
    return Settings(
        api_key=env.get("LLM_API_KEY", "").strip(),
        base_url=env.get("LLM_BASE_URL", "").strip() or None,
        model=env.get("LLM_MODEL", "openai/gpt-5-mini").strip(),
        temperature=_optional_float(env, "LLM_TEMPERATURE"),
        structured_outputs=env.get("LLM_STRUCTURED_OUTPUTS", "true").strip().lower() in {"1", "true", "yes"},
        timeout=_number(env, "LLM_TIMEOUT", "120", float),
        max_attempts=max(1, _number(env, "LLM_MAX_ATTEMPTS", "2", int)),
        max_tokens=_number(env, "LLM_MAX_TOKENS", "16000", int),
        reasoning_effort=env.get("LLM_REASONING_EFFORT", "low").strip() or None,
    )
