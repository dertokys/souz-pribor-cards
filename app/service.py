from functools import lru_cache

from .config import ConfigError, get_settings
from .generator import CardGenerator
from .input_parser import parse_product
from .llm import LLMConfigError, OpenAICompatibleClient
from .schemas import CardResult


@lru_cache(maxsize=1)
def get_generator() -> CardGenerator:
    try:
        settings = get_settings()
    except ConfigError as e:
        raise LLMConfigError(str(e)) from e
    return CardGenerator(OpenAICompatibleClient(settings), max_attempts=settings.max_attempts)


def generate_card(raw: str | bytes | dict, generator: CardGenerator | None = None) -> CardResult:
    product, missing = parse_product(raw)
    try:
        return (generator or get_generator()).generate(product, missing)
    except LLMConfigError:
        get_generator.cache_clear()
        raise
