from app.schemas import LLMCard
from app.validator import find_conflicts, fix_mixed_script, norm, numbers, source_numbers, ungrounded_numbers, validate

from .conftest import make_card, make_description


def test_numbers_normalized():
    assert numbers("0,5 % и 1,0 МПа, 4...20 мА") == {"0.5", "1", "4", "20"}
    assert "500000" in numbers("не менее 500 000 ч")


def test_norm_handles_lookalikes_and_dashes():
    assert norm("M20х1,5") == norm("М20x1.5")
    assert norm("–40…+80 °С") == norm("-40...+80 °c")


def test_fix_mixed_script():
    assert fix_mixed_script("защитa от влаги, DPt100Ω, SSR") == "защита от влаги, DPt100Ω, SSR"
    assert fix_mixed_script("ОВЕН ПД100") == "ОВЕН ПД100"
    assert fix_mixed_script("ПИД‑регулирование") == "ПИД-регулирование"


def test_placeholder_spec_names_dropped(product):
    card = make_card(key_specs=[
        {"name": "Отсутствующий типовой параметр", "value": "данных нет", "source": "none"},
        {"name": "диапазон измерений", "value": "данных нет", "source": "none"},
    ])
    lines = validate(LLMCard(**card), product).spec_lines
    assert [s.name for s in lines] == ["Диапазон измерений"]


def test_ungrounded_numbers(product):
    allowed = source_numbers(product)
    assert ungrounded_numbers("сигнал 4...20 мА, до 1 МПа", allowed) == []
    assert ungrounded_numbers("погрешность 0,25 %, IP67", allowed) == ["67", "0.25"]
    assert ungrounded_numbers("наработка 500000 ч", allowed) == []


def test_clean_card_has_no_issues(product):
    report = validate(LLMCard(**make_card()), product)
    assert report.issues == []
    statuses = {s.name: s.status for s in report.spec_lines}
    assert statuses == {
        "Выходной сигнал": "ok",
        "Степень защиты": "ok",
        "Материал мембраны": "from_text",
        "Погрешность": "no_data",
    }


def test_spec_value_replaced_with_source(product):
    card = make_card(key_specs=[{"name": "Питание", "value": "24 В", "source": "specs:Напряжение питания"}])
    report = validate(LLMCard(**card), product)
    line = report.spec_lines[0]
    assert line.value == "12…36 В постоянного тока"
    assert line.status == "corrected"
    assert report.spec_warnings


def test_unknown_spec_key_is_issue(product):
    card = make_card(key_specs=[{"name": "Погрешность", "value": "0,5 %", "source": "specs:Погрешность"}])
    report = validate(LLMCard(**card), product)
    assert report.spec_lines == []
    assert any("не найден в specs" in i for i in report.issues)


def test_text_spec_with_foreign_number_rejected(product):
    card = make_card(key_specs=[{"name": "Диапазон", "value": "0…2,5 МПа", "source": "text"}])
    report = validate(LLMCard(**card), product)
    assert report.spec_lines == []
    assert any("не найдено в описании" in i for i in report.issues)


def test_text_spec_without_support_rejected(product):
    card = make_card(key_specs=[{"name": "Материал корпуса", "value": "алюминиевый сплав", "source": "text"}])
    assert validate(LLMCard(**card), product).spec_lines == []


def test_text_spec_rejected_when_description_empty(product):
    product.description = ""
    card = make_card(key_specs=[{"name": "Материал мембраны", "value": "нержавеющая сталь", "source": "text"}])
    assert validate(LLMCard(**card), product).spec_lines == []


def test_text_spec_can_come_from_product_type(product):
    card = make_card(key_specs=[{"name": "Измеряемая величина", "value": "давления", "source": "text"}])
    report = validate(LLMCard(**card), product)
    assert report.spec_lines[0].status == "from_text"


def test_identity_fields_are_not_specs(product):
    card = make_card(key_specs=[
        {"name": "Производитель", "value": "данных нет", "source": "none"},
        {"name": "Модель", "value": "ПД100", "source": "text"},
    ])
    report = validate(LLMCard(**card), product)
    assert report.spec_lines == []
    assert sum("не техническая характеристика" in i for i in report.issues) == 2


def test_find_conflicts_between_specs_and_description(product):
    conflicts = find_conflicts(product)
    assert len(conflicts) == 1
    assert conflicts[0].startswith("Среднее время наработки на отказ")
    assert "500 000" in conflicts[0] and "50 000" in conflicts[0]


def test_invented_number_in_text_is_issue(product):
    card = make_card(seo_description=make_description("Погрешность составляет 0,25 %. "))
    report = validate(LLMCard(**card), product)
    assert any(i.startswith("seo_description") and "0.25" in i for i in report.issues)


def test_length_limits(product):
    card = make_card(seo_title="Т" * 71, seo_description="Коротко.", search_queries=["a", "b"])
    issues = validate(LLMCard(**card), product).issues
    assert any(i.startswith("seo_title") for i in issues)
    assert any(i.startswith("seo_description") for i in issues)
    assert any(i.startswith("search_queries") for i in issues)


def test_bad_source_is_issue(product):
    card = make_card(key_specs=[{"name": "Давление", "value": "1,0 МПа", "source": "name"}])
    assert any("недопустимый source" in i for i in validate(LLMCard(**card), product).issues)
