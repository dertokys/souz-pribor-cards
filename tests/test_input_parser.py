import json

import pytest

from app.input_parser import InputError, parse_product


def test_valid_input():
    product, missing = parse_product(json.dumps({
        "name": "TC4S-14R",
        "manufacturer": "Autonics",
        "specs": {"Размер": "48×48мм", "Период измерения": 100},
        "description": "Контроллер",
    }))
    assert product.name == "TC4S-14R"
    assert product.specs == {"Размер": "48×48мм", "Период измерения": "100"}
    assert missing == []


def test_invalid_json_reports_position():
    with pytest.raises(InputError) as e:
        parse_product('{"name": "x",}')
    assert "Некорректный JSON" in e.value.message
    assert "строка 1" in e.value.message


def test_non_utf8_body():
    with pytest.raises(InputError) as e:
        parse_product('{"name": "ОВЕН"}'.encode("cp1251"))
    assert "UTF-8" in e.value.message


def test_utf8_bom_accepted():
    product, _ = parse_product('{"name": "ОВЕН"}'.encode("utf-8-sig"))
    assert product.name == "ОВЕН"


def test_empty_body():
    with pytest.raises(InputError):
        parse_product("   ")


def test_not_an_object():
    with pytest.raises(InputError):
        parse_product("[1, 2]")


def test_name_required():
    with pytest.raises(InputError) as e:
        parse_product({"name": "  ", "manufacturer": "ОВЕН"})
    assert any(d.startswith("name") for d in e.value.details)


def test_wrong_types_collected():
    with pytest.raises(InputError) as e:
        parse_product({"name": "x", "manufacturer": ["a"], "specs": {"A": {"nested": 1}}})
    assert len(e.value.details) == 2


def test_missing_fields_listed():
    product, missing = parse_product({"name": "ТРМ500", "specs": {"Питание": "", "Вход": "-", "Выход": "реле"}})
    fields = [m.field for m in missing]
    assert fields[:2] == ["description", "manufacturer"]
    assert "specs.Питание" in fields and "specs.Вход" in fields
    assert product.specs == {"Выход": "реле"}


def test_no_specs_is_missing_not_error():
    _, missing = parse_product({"name": "ТРМ500", "manufacturer": "ОВЕН", "description": "Регулятор"})
    assert [m.field for m in missing] == ["specs"]


def test_specs_as_list_of_pairs():
    product, _ = parse_product({"name": "x", "specs": [{"name": "IP", "value": "IP65"}]})
    assert product.specs == {"IP": "IP65"}
