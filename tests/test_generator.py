import pytest

from app.generator import CardGenerator, cut_to_words
from app.llm import LLMBadResponse, LLMRateLimited, LLMUnavailable
from app.render import to_markdown

from .conftest import FakeLLM, make_card, make_description


def test_success_first_attempt(product):
    llm = FakeLLM([make_card()])
    card = CardGenerator(llm).generate(product, [])
    assert card.quality.attempts == 1
    assert card.quality.warnings == []
    assert len(llm.calls) == 1
    assert "<INPUT>" in llm.calls[0][1]["content"]


def test_repair_round_fixes_issues(product):
    bad = make_card(seo_title="Т" * 80)
    llm = FakeLLM([bad, make_card()])
    card = CardGenerator(llm, max_attempts=2).generate(product, [])
    assert card.quality.attempts == 2
    assert card.quality.warnings == []
    repair = llm.calls[1][-1]["content"]
    assert "seo_title: 80 символов" in repair
    assert card.quality.repaired_issues == ["seo_title: 80 символов, нужно не больше 70"]


def test_invalid_json_then_valid(product):
    llm = FakeLLM(["это не json", make_card()])
    card = CardGenerator(llm, max_attempts=2).generate(product, [])
    assert card.quality.attempts == 2
    assert "Ответ не разобран" in llm.calls[1][-1]["content"]


def test_invalid_json_every_time(product):
    llm = FakeLLM(["{", '{"seo_title": 1}'])
    with pytest.raises(LLMBadResponse):
        CardGenerator(llm, max_attempts=2).generate(product, [])


def test_unfixed_invented_numbers_are_removed(product):
    invented = make_card(
        seo_title="Датчик давления ОВЕН ПД100 с погрешностью 0,25 %",
        seo_description=make_description("Погрешность составляет 0,25 %. "),
        search_queries=["пд100", "датчик давления ip67", "датчик давления овен", "пд100 1 мпа"],
    )
    llm = FakeLLM([invented, invented])
    card = CardGenerator(llm, max_attempts=2).generate(product, [])
    assert "0,25" not in card.seo_title
    assert "0,25" not in card.seo_description
    assert "датчик давления ip67" not in card.search_queries
    assert card.quality.needs_review is True
    assert any("удалено предложение" in w for w in card.quality.warnings)


def test_spec_values_always_from_input(product):
    data = make_card(key_specs=[{"name": "Питание", "value": "24 В DC", "source": "specs:Напряжение питания"}])
    card = CardGenerator(FakeLLM([data, data])).generate(product, [])
    assert card.key_specs[0].value == "12…36 В постоянного тока"


def test_llm_errors_propagate(product):
    with pytest.raises(LLMUnavailable):
        CardGenerator(FakeLLM([LLMUnavailable("нет сети")])).generate(product, [])


def test_conflicts_merged_without_duplicates(product):
    llm_conflicts = [
        "Среднее время наработки на отказ: в характеристиках «500 000 ч», в описании «50 000 ч»",
        "Тип индикатора: в характеристиках «светодиодный», в описании «ЖК»",
    ]
    card = CardGenerator(FakeLLM([make_card(data_conflicts=llm_conflicts)])).generate(product, [])
    assert len(card.data_conflicts) == 2
    assert card.data_conflicts[1].startswith("Тип индикатора")


def test_absent_value_is_not_a_conflict(product):
    data = make_card(data_conflicts=[
        "Точка росы: в характеристиках «данных нет», в описании «измерение точки росы»",
        "Наличие манометра: в характеристиках «Предустановленный», в описании «Отсутствие манометра»",
    ])
    card = CardGenerator(FakeLLM([data])).generate(product, [])
    assert not any("Точка росы" in c for c in card.data_conflicts)
    assert any("Наличие манометра" in c for c in card.data_conflicts)


def test_llm_conflicts_ignored_without_specs(product):
    product.specs = {}
    data = make_card(key_specs=[], data_conflicts=["тип: в характеристиках «данных нет», в описании «датчик»"])
    card = CardGenerator(FakeLLM([data, data])).generate(product, [])
    assert card.data_conflicts == []


def test_markdown_contains_sections(product):
    card = CardGenerator(FakeLLM([make_card()])).generate(product, [])
    md = to_markdown(card)
    for section in ["SEO-заголовок", "SEO-описание", "Ключевые характеристики", "Поисковые запросы", "Для менеджера", "Отсутствующие данные", "Противоречия"]:
        assert section in md
    assert "Погрешность — важный для выбора параметр" in md
    assert "Требует проверки:** противоречия во входных данных (1)" in md


def test_long_description_trimmed_by_sentences(product):
    long_text = make_description() + "\n\n" + " ".join(["Прибор работает в системах автоматизации."] * 12)
    data = make_card(seo_description=long_text)
    card = CardGenerator(FakeLLM([data, data])).generate(product, [])
    assert 800 <= card.quality.seo_description_length <= 1200
    assert card.seo_description.endswith(".")
    assert any("убраны последние предложения" in w for w in card.quality.warnings)


def test_dropped_identity_rows_do_not_require_review(product):
    product.description = "Мембрана из нержавеющей стали."
    data = make_card(key_specs=[{"name": "Модель", "value": "ПД100", "source": "text"}])
    card = CardGenerator(FakeLLM([data, data])).generate(product, [])
    assert card.quality.warnings == []
    assert card.quality.needs_review is False


def test_heading_and_fallback_title_without_duplicate_brand():
    from app.generator import fallback_title
    from app.schemas import ProductInput

    product = ProductInput(name="МЕГЕОН 70083", manufacturer="МЕГЕОН", product_type="токоизмерительные клещи")
    assert fallback_title(product) == "Токоизмерительные клещи МЕГЕОН 70083"
    card = CardGenerator(FakeLLM([make_card(), make_card()])).generate(product, [])
    assert to_markdown(card).startswith("# Черновик карточки: МЕГЕОН 70083\n")


def test_cut_to_words():
    assert cut_to_words("один два три четыре", 12) == "один два три"
    assert cut_to_words("один два три четыре", 11) == "один два"
    assert len(cut_to_words("а" * 100, 70)) <= 70


def test_failed_repair_call_keeps_first_card(product):
    llm = FakeLLM([make_card(seo_title="Т" * 80), LLMRateLimited("лимит")])
    card = CardGenerator(llm, max_attempts=2).generate(product, [])
    assert card.quality.attempts == 1
    assert len(card.seo_title) <= 70
    assert any("Повторный запрос к модели не выполнен" in w for w in card.quality.warnings)


def test_needs_review_when_only_conflicts(product):
    card = CardGenerator(FakeLLM([make_card()])).generate(product, [])
    assert card.quality.warnings == []
    assert card.data_conflicts
    assert card.quality.needs_review is True


def test_needs_review_false_without_conflicts(product):
    product.description = "Мембрана из нержавеющей стали."
    card = CardGenerator(FakeLLM([make_card()])).generate(product, [])
    assert card.quality.needs_review is False


def test_issue_not_reported_repaired_if_still_failing(product):
    first = make_card(seo_description="Коротко. " * 10)
    second = make_card(seo_description="Чуть длиннее, но всё ещё мало. " * 5)
    card = CardGenerator(FakeLLM([first, second]), max_attempts=2).generate(product, [])
    assert not any(i.startswith("seo_description") for i in card.quality.repaired_issues)


def test_missing_fields_deduplicated(product):
    from app.schemas import MissingField

    data = make_card(key_specs=[
        {"name": "Диаметр", "value": "данных нет", "source": "none"},
        {"name": "Погрешность", "value": "данных нет", "source": "none"},
    ])
    card = CardGenerator(FakeLLM([data])).generate(product, [MissingField(field="specs.Диаметр", reason="значение не указано")])
    assert [m.field for m in card.missing_fields] == ["specs.Диаметр", "Погрешность"]


def test_model_name_numbers_cannot_become_specs_in_text(product):
    decoded = make_card(seo_description=make_description("Температура среды до 115 °С. "))
    card = CardGenerator(FakeLLM([decoded, decoded])).generate(product, [])
    assert "115 °С" not in card.seo_description


def test_meta_sentence_removed_if_not_repaired(product):
    data = make_card(seo_description=make_description("В описании нет подробных параметров корпуса. "))
    card = CardGenerator(FakeLLM([data, data])).generate(product, [])
    assert "В описании" not in card.seo_description
    assert any("служебное предложение" in w for w in card.quality.warnings)


def test_duplicate_queries_removed(product):
    data = make_card(search_queries=["пд100", "ПД100", "датчик давления овен", "преобразователь давления овен"])
    card = CardGenerator(FakeLLM([data, data])).generate(product, [])
    assert card.search_queries == ["пд100", "датчик давления овен", "преобразователь давления овен"]


def test_markdown_table_escapes_emphasis():
    from app.render import _cell

    assert _cell("MINI: G1/8*, G1/4_x | y") == r"MINI: G1/8\*, G1/4\_x \| y"
