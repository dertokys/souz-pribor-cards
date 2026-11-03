import json
from typing import Any

from .schemas import MissingField, ProductInput

TEXT_FIELDS = ("name", "manufacturer", "product_type", "category", "sku", "url", "description")
EMPTY_MARKERS = {"", "-", "—", "–", "н/д", "нет данных", "данных нет", "null", "none", "n/a"}


class InputError(ValueError):
    def __init__(self, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip().lower() in EMPTY_MARKERS)


def _scalar_to_str(value: Any) -> str | None:
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, list) and all(isinstance(v, (str, int, float)) and not isinstance(v, bool) for v in value):
        return ", ".join(str(v).strip() for v in value if str(v).strip())
    return None


def _normalize_specs(raw: Any, errors: list[str], missing: list[MissingField]) -> dict[str, str]:
    if raw is None:
        return {}
    if isinstance(raw, list):
        pairs = []
        for i, item in enumerate(raw):
            if isinstance(item, dict) and "name" in item:
                pairs.append((item.get("name"), item.get("value")))
            else:
                errors.append(f"specs[{i}]: ожидается объект {{\"name\": ..., \"value\": ...}}")
        raw = dict(pairs)
    if not isinstance(raw, dict):
        errors.append("specs: ожидается объект {\"характеристика\": \"значение\"}")
        return {}

    specs: dict[str, str] = {}
    for key, value in raw.items():
        key = " ".join(str(key).split())
        if not key:
            errors.append("specs: пустое название характеристики")
            continue
        if _is_empty(value):
            missing.append(MissingField(field=f"specs.{key}", reason="значение не указано"))
            continue
        text = _scalar_to_str(value)
        if text is None:
            errors.append(f"specs.{key}: значение должно быть строкой, числом или списком строк")
            continue
        if not text or text.lower() in EMPTY_MARKERS:
            missing.append(MissingField(field=f"specs.{key}", reason="значение не указано"))
            continue
        specs[key] = text
    return specs


def parse_product(raw: str | bytes | dict) -> tuple[ProductInput, list[MissingField]]:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            raise InputError("Тело запроса должно быть в кодировке UTF-8") from e
    if isinstance(raw, str):
        if not raw.strip():
            raise InputError("Пустой запрос: ожидается JSON с данными товара")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise InputError(f"Некорректный JSON: {e.msg} (строка {e.lineno}, позиция {e.colno})") from e
    else:
        data = raw

    if not isinstance(data, dict):
        raise InputError("Ожидается JSON-объект вида {\"name\": ..., \"manufacturer\": ..., \"specs\": {...}, \"description\": ...}")

    errors: list[str] = []
    missing: list[MissingField] = []
    fields: dict[str, str] = {}
    for name in TEXT_FIELDS:
        value = data.get(name)
        if _is_empty(value):
            fields[name] = ""
            continue
        text = _scalar_to_str(value)
        if text is None or isinstance(value, list):
            errors.append(f"{name}: ожидается строка")
            continue
        fields[name] = text

    specs = _normalize_specs(data.get("specs"), errors, missing)

    if not fields.get("name"):
        errors.insert(0, "name: обязательное поле — без названия товара карточку не собрать")
    if errors:
        raise InputError("Входные данные не прошли проверку", errors)

    if not fields.get("manufacturer"):
        missing.insert(0, MissingField(field="manufacturer", reason="производитель не указан"))
    if not specs:
        missing.insert(0, MissingField(field="specs", reason="технические характеристики не переданы"))
    if not fields.get("description"):
        missing.insert(0, MissingField(field="description", reason="описание товара отсутствует"))

    return ProductInput(**fields, specs=specs), missing
