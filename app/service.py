from functools import lru_cache

from .config import get_settings
from .generator import CardGenerator
from .input_parser import parse_product
from .llm import OpenAICompatibleClient
from .schemas import CardResult


@lru_cache(maxsize=1)
def get_generator() -> CardGenerator:
    settings = get_settings()
    return CardGenerator(OpenAICompatibleClient(settings), max_attempts=settings.max_attempts)


def generate_card(raw: str | bytes | dict, generator: CardGenerator | None = None) -> CardResult:
    product, missing = parse_product(raw)
    return (generator or get_generator()).generate(product, missing)
