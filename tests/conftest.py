import json

import pytest

from app.schemas import ProductInput

SPECS = {
    "Выходной сигнал постоянного тока": "4...20 мА, 2-х проводная схема",
    "Напряжение питания": "12…36 В постоянного тока",
    "Степень защиты корпуса": "IP65",
    "Верхний предел измерений": "1 МПа",
    "Среднее время наработки на отказ": "не менее 500 000 ч",
}

DESCRIPTION = (
    "Преобразователь избыточного давления предназначен для измерения в диапазоне 0…1,0 МПа. "
    "Мембрана из нержавеющей стали.\n"
    "Степень защиты корпуса: IP65\n"
    "Среднее время наработки на отказ: не менее 50 000 ч"
)


@pytest.fixture
def product() -> ProductInput:
    return ProductInput(
        name="ПД100-ДИ1,0-115-0,5",
        manufacturer="ОВЕН",
        product_type="преобразователь давления",
        specs=dict(SPECS),
        description=DESCRIPTION,
    )


def make_description(extra: str = "") -> str:
    base = (
        "Преобразователь давления ОВЕН ПД100-ДИ1,0-115-0,5 измеряет избыточное давление до 1 МПа "
        "и выдаёт сигнал 4...20 мА по двухпроводной схеме. Корпус со степенью защиты IP65. "
    )
    text = base + extra
    while len(text) < 850:
        text += "Прибор подходит для систем автоматического контроля и регулирования технологических процессов. "
    return text.strip()


def make_card(**overrides) -> dict:
    card = {
        "seo_title": "Преобразователь давления ОВЕН ПД100-ДИ1,0-115-0,5, 4...20 мА",
        "seo_description": make_description(),
        "key_specs": [
            {"name": "Выходной сигнал", "value": "4...20 мА, 2-х проводная схема", "source": "specs:Выходной сигнал постоянного тока"},
            {"name": "Степень защиты", "value": "IP65", "source": "specs:Степень защиты корпуса"},
            {"name": "Материал мембраны", "value": "нержавеющая сталь", "source": "text"},
            {"name": "Погрешность", "value": "данных нет", "source": "none"},
        ],
        "search_queries": ["пд100-ди1,0-115-0,5", "датчик давления овен пд100", "преобразователь давления 4-20 ма"],
        "commercial": {
            "summary": "Датчик избыточного давления в полевом корпусе для систем автоматики.",
            "target_customers": ["инженеры КИПиА", "системные интеграторы"],
            "tasks": ["контроль давления в трубопроводах", "передача сигнала 4...20 мА в ПЛК"],
        },
        "data_conflicts": [],
    }
    card.update(overrides)
    return card


class FakeLLM:
    model = "fake-model"
    structured_outputs = True

    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def complete(self, messages: list[dict]) -> str:
        self.calls.append([dict(m) for m in messages])
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
