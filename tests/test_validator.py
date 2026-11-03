from app.schemas import LLMCard
from app.schemas import ProductInput
from app.validator import NumberCheck, find_conflicts, fix_mixed_script, mixed_script_words, norm, numbers, validate

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
    assert fix_mixed_script("Autoniсs") == "Autonics"
    assert mixed_script_words(fix_mixed_script("ovен")) == ["оvен"]


def test_placeholder_spec_names_dropped(product):
    card = make_card(key_specs=[
        {"name": "Отсутствующий типовой параметр", "value": "данных нет", "source": "none"},
        {"name": "Остальные важные параметры", "value": "данных нет", "source": "none"},
        {"name": "диапазон измерений", "value": "данных нет", "source": "none"},
        {"name": "Время отклика (обычно важный параметр)", "value": "данных нет", "source": "none"},
    ])
    lines = validate(LLMCard(**card), product).spec_lines
    assert [s.name for s in lines] == ["Диапазон измерений", "Время отклика"]


def test_ungrounded_numbers(product):
    check = NumberCheck(product)
    assert check("сигнал 4...20 мА, до 1 МПа") == []
    assert check("погрешность 0,25 %, IP67") == ["67", "0.25"]
    assert check("наработка 500000 ч") == []
    assert check("наработка 500 000 ч") == []


def test_numbers_from_model_name_only_inside_designation(product):
    check = NumberCheck(product)
    assert check("ОВЕН ПД100-ДИ1,0-115-0,5 и датчик пд100") == []
    assert check("температура среды до 115 °С") == ["115"]


def test_conflicting_description_value_not_allowed(product):
    check = NumberCheck(product)
    assert check("наработка на отказ 50 000 ч") == ["50"]
    assert check("наработка на отказ 50000 ч") == ["50000"]


def test_adjacent_numbers_not_merged(product):
    assert NumberCheck(product)("корпус IP65 500 раз") == []


def test_clean_card_has_no_issues(product):
    report = validate(LLMCard(**make_card()), product)
    assert report.issues == []
    statuses = {s.name: s.status for s in report.spec_lines}
    assert statuses == {
        "Выходной сигнал постоянного тока": "ok",
        "Степень защиты корпуса": "ok",
        "Материал мембраны": "from_text",
        "Погрешность": "no_data",
    }


def test_spec_value_replaced_with_source(product):
    card = make_card(key_specs=[{"name": "Питание", "value": "24 В", "source": "specs:Напряжение питания"}])
    report = validate(LLMCard(**card), product)
    line = report.spec_lines[0]
    assert line.value == "12…36 В постоянного тока"
    assert line.status == "corrected"
    assert line.name == "Напряжение питания"
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
        {"name": "Категория прибора", "value": "данных нет", "source": "none"},
        {"name": "Тип выхода", "value": "данных нет", "source": "none"},
    ])
    report = validate(LLMCard(**card), product)
    assert [s.name for s in report.spec_lines] == ["Тип выхода"]
    assert sum("не техническая характеристика" in i for i in report.issues) == 3


def test_find_conflicts_between_specs_and_description(product):
    conflicts = find_conflicts(product)
    assert len(conflicts) == 1
    assert conflicts[0].text.startswith("Среднее время наработки на отказ")
    assert "500 000" in conflicts[0].text and "50 000" in conflicts[0].text


def test_shorter_description_value_is_not_conflict():
    product = ProductInput(
        name="TC4S",
        specs={"Гистерезис": "1…100℃ (0.1…50.0℃) изменяемый", "Индикатор": "светодиодный"},
        description="Гистерезис: 1…100℃\nИндикатор: ЖК",
    )
    assert find_conflicts(product) == []


def test_none_for_existing_spec_gets_real_value(product):
    card = make_card(key_specs=[{"name": "Напряжение питания", "value": "данных нет", "source": "none"}])
    report = validate(LLMCard(**card), product)
    assert report.spec_lines[0].value == "12…36 В постоянного тока"
    assert report.spec_lines[0].status == "corrected"
    assert report.issues == []


def test_none_matches_key_with_units_in_parentheses():
    product = ProductInput(name="АКИП-4131", specs={"Масса (кг)": "2,6"})
    card = make_card(key_specs=[{"name": "Масса", "value": "данных нет", "source": "none"}])
    line = validate(LLMCard(**card), product).spec_lines[0]
    assert (line.name, line.value, line.status) == ("Масса (кг)", "2,6", "corrected")


def test_shortened_spec_name_restored_from_key():
    product = ProductInput(name="АКИП-1162", specs={"19” форм фактор": "да"})
    card = make_card(key_specs=[{"name": "Форм фактор", "value": "да", "source": "specs:19” форм фактор"}])
    assert validate(LLMCard(**card), product).spec_lines[0].name == "19” форм фактор"


def test_spec_name_keeps_units_from_key():
    product = ProductInput(name="КМС", specs={"Время измерения параметров, с, не более": "1"})
    card = make_card(key_specs=[{"name": "Время измерения параметров", "value": "1", "source": "specs:Время измерения параметров, с, не более"}])
    line = validate(LLMCard(**card), product).spec_lines[0]
    assert line.name == "Время измерения параметров, с, не более"


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


def test_mixed_script_keeps_source_words_and_maps_m():
    assert fix_mixed_script("Термопара ДТПS155", keep={"дтпs"}) == "Термопара ДТПS155"
    assert mixed_script_words("ДТПS155", keep={"дтпs"}) == []
    assert fix_mixed_script("Теmпературный") == "Температурный"


def test_no_data_prefix_and_commercial_fields():
    product = ProductInput(name="МЕГЕОН 08014", specs={"Диапазон": "0…30 %"})
    card = make_card(key_specs=[
        {"name": "Данных нет — степень защиты", "value": "данных нет", "source": "none"},
        {"name": "Гарантийный срок", "value": "данных нет", "source": "none"},
        {"name": "Цена", "value": "данных нет", "source": "none"},
    ])
    report = validate(LLMCard(**card), product)
    assert [s.name for s in report.spec_lines] == ["Степень защиты"]
