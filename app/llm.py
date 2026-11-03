from typing import Protocol

import openai

from .config import Settings
from .prompts import CARD_JSON_SCHEMA


class LLMError(Exception):
    status_code = 502

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class LLMConfigError(LLMError):
    status_code = 500


class LLMRateLimited(LLMError):
    status_code = 429


class LLMUnavailable(LLMError):
    status_code = 503


class LLMBadResponse(LLMError):
    status_code = 502


class LLMClient(Protocol):
    model: str
    structured_outputs: bool

    def complete(self, messages: list[dict]) -> str: ...


class OpenAICompatibleClient:
    def __init__(self, settings: Settings):
        if not settings.api_key:
            raise LLMConfigError("Не задан LLM_API_KEY: скопируйте .env.example в .env и впишите ключ")
        self.model = settings.model
        self.structured_outputs = settings.structured_outputs
        self._temperature = settings.temperature
        self._max_tokens = settings.max_tokens
        self._reasoning_effort = settings.reasoning_effort
        self._client = openai.OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.timeout,
            max_retries=2,
        )

    def complete(self, messages: list[dict]) -> str:
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self._max_tokens,
            "response_format": (
                {"type": "json_schema", "json_schema": CARD_JSON_SCHEMA}
                if self.structured_outputs
                else {"type": "json_object"}
            ),
        }
        if self._temperature is not None:
            kwargs["temperature"] = self._temperature
        if self._reasoning_effort:
            kwargs["reasoning_effort"] = self._reasoning_effort

        try:
            response = self._client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as e:
            raise LLMConfigError("LLM API отклонил ключ (401): проверьте LLM_API_KEY") from e
        except openai.PermissionDeniedError as e:
            raise LLMConfigError(f"Нет доступа к модели {self.model} (403): {e.message}") from e
        except openai.RateLimitError as e:
            raise LLMRateLimited("Превышен лимит запросов или закончился баланс у провайдера LLM (429)") from e
        except openai.APITimeoutError as e:
            raise LLMUnavailable("LLM API не ответил за отведённое время") from e
        except openai.APIConnectionError as e:
            raise LLMUnavailable("Не удалось подключиться к LLM API: проверьте LLM_BASE_URL и сеть") from e
        except openai.BadRequestError as e:
            raise LLMBadResponse(f"LLM API отклонил запрос (400): {e.message}") from e
        except openai.APIStatusError as e:
            if e.status_code >= 500:
                raise LLMUnavailable(f"Ошибка на стороне LLM API ({e.status_code})") from e
            raise LLMBadResponse(f"LLM API вернул ошибку {e.status_code}: {e.message}") from e

        if not response.choices:
            raise LLMBadResponse("LLM API вернул ответ без вариантов")
        choice = response.choices[0]
        if getattr(choice.message, "refusal", None):
            raise LLMBadResponse(f"Модель отказалась отвечать: {choice.message.refusal}")
        if choice.finish_reason == "length":
            raise LLMBadResponse("Ответ модели обрезан по лимиту токенов: увеличьте LLM_MAX_TOKENS")
        if not choice.message.content:
            raise LLMBadResponse("Модель вернула пустой ответ")
        return choice.message.content
