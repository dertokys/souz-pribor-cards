import pytest

from app.generator import CardGenerator, cut_to_words
from app.llm import LLMBadResponse, LLMUnavailable
from app.render import to_markdown

from .conftest import FakeLLM, make_card, make_description


def test_success_first_attempt(product):
    llm = FakeLLM([make_card()])
    card = CardGenerator(llm).generate(product, [])
    assert card.quality.attempts == 1
    assert card.quality.needs_review is False
    assert len(llm.calls) == 1
    assert "<INPUT>" in llm.calls[0][1]["content"]


def test_repair_round_fixes_issues(product):
    bad = make_card(seo_title="Т" * 80)
    llm = FakeLLM([bad, make_card()])
    card = CardGenerator(llm, max_attempts=2).generate(product, [])
    assert card.quality.attempts == 2
    assert card.quality.needs_review is False
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
    assert "Погрешность — данных нет" in md


def test_long_description_trimmed_by_sentences(product):
    long_text = make_description() + "\n\n" + " ".join(["Прибор работает в системах автоматизации."] * 12)
    data = make_card(seo_description=long_text)
    card = CardGenerator(FakeLLM([data, data])).generate(product, [])
    assert 800 <= card.quality.seo_description_length <= 1200
    assert card.seo_description.endswith(".")
    assert any("убраны последние предложения" in w for w in card.quality.warnings)


def test_cut_to_words():
    assert cut_to_words("один два три четыре", 12) == "один два три"
    assert cut_to_words("один два три четыре", 11) == "один два"
    assert len(cut_to_words("а" * 100, 70)) <= 70
