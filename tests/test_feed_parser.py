import sys
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from feed_to_input import parse_description, parse_specs

PAGE = """
<div class="characteristics">
  <div class="characteristics__item">
    <span class="characteristics__name">Исполнение корпуса:</span>
    <span class="characteristics__desc"><a>Врезной в щит</a></span>
  </div>
  <div class="characteristics__item">
    <span class="characteristics__name">Артикул:</span>
    <span class="characteristics__desc">A1500001030</span>
  </div>
</div>
<div id="description">
  <div class="product-description">
    <table><tr><td>СНЯТ С ПРОИЗВОДСТВА</td></tr></table>
    <p>Преобразователь давления для сложных условий.</p>
    <ul><li>Защита от гидроударов</li></ul>
  </div>
</div>
<div id="specifications"><table>
  <tr><td><p>Наименование</p></td><td><p>Значение</p></td></tr>
  <tr><td><p>Тип входа</p></td><td>Термопара: K, J<br>RTD: Pt100</td></tr>
  <tr><td><p>Устойчивость к механическим</p></td><td><p>группа V3</p></td></tr>
  <tr><td><p>воздействиям</p></td><td><p>по ГОСТ Р 52931</p></td></tr>
  <tr><td><p>Протоколы связи</p></td><td><p>ModBus-RTU;</p><p>OWEN,</p></td></tr>
  <tr><td colspan="2"><b>Питание</b></td></tr>
</table></div>
"""


def test_parse_specs():
    specs = parse_specs(BeautifulSoup(PAGE, "html.parser"))
    assert specs == {
        "Тип входа": "Термопара: K, J; RTD: Pt100",
        "Устойчивость к механическим воздействиям": "группа V3 по ГОСТ Р 52931",
        "Протоколы связи": "ModBus-RTU; OWEN",
        "Исполнение корпуса": "Врезной в щит",
    }


MULTI = """
<div id="specifications"><table>
  <tr><td colspan="9">Измерение постоянного напряжения</td></tr>
  <tr><td colspan="2">Диапазон</td><td colspan="3">Разрешение</td><td colspan="3">Точность</td></tr>
  <tr><td colspan="2">4В</td><td colspan="3">1мВ</td><td colspan="3" rowspan="2">±0,8% + 2 е.м.р.</td></tr>
  <tr><td colspan="2">40В</td><td colspan="3">10мВ</td></tr>
  <tr><td colspan="9">Измерение тока</td></tr>
  <tr><td colspan="2">40А</td><td colspan="3">10мА</td><td colspan="3">± 2%</td></tr>
</table><table>
  <tr><td>Расход воды, м3/ч:</td><td></td></tr>
  <tr><td>- наименьший Q min</td><td>2,4</td></tr>
  <tr><td>- номинальный Qn</td><td>70</td></tr>
  <tr><td>Цена импульса</td><td>100л/имп</td></tr>
</table></div>
"""


def test_parse_multicolumn_and_grouped_tables():
    specs = parse_specs(BeautifulSoup(MULTI, "html.parser"))
    assert specs == {
        "Измерение постоянного напряжения: Диапазон 4В": "Разрешение: 1мВ; Точность: ±0,8% + 2 е.м.р.",
        "Измерение постоянного напряжения: Диапазон 40В": "Разрешение: 10мВ; Точность: ±0,8% + 2 е.м.р.",
        "Измерение тока: Диапазон 40А": "Разрешение: 10мА; Точность: ± 2%",
        "Расход воды, м3/ч — наименьший Q min": "2,4",
        "Расход воды, м3/ч — номинальный Qn": "70",
        "Цена импульса": "100л/имп",
    }


FAMILY = """
<div id="specifications"><table>
  <tr><td>Параметр</td><td colspan="5">Значение</td></tr>
  <tr><td>Типоразмер</td><td colspan="2">MINI</td><td colspan="2">MIDI</td><td>MAXI</td></tr>
  <tr><td>Присоединительный размер</td><td>G1/8</td><td>G3/8</td><td>G3/8</td><td>G1/2</td><td>G1</td></tr>
  <tr><td>Гистерезис, bar</td><td colspan="4">0,2</td><td>0,4</td></tr>
  <tr><td>Рабочее давление, bar</td><td colspan="5">До 16</td></tr>
  <tr><td colspan="6">Питание</td></tr>
  <tr><td>Напряжение</td><td colspan="5">24 В</td></tr>
</table></div>
"""


def test_parse_family_matrix_table():
    specs = parse_specs(BeautifulSoup(FAMILY, "html.parser"))
    assert specs == {
        "Присоединительный размер": "MINI: G1/8, G3/8; MIDI: G3/8, G1/2; MAXI: G1",
        "Гистерезис, bar": "MINI: 0,2; MIDI: 0,2; MAXI: 0,4",
        "Рабочее давление, bar": "До 16",
        "Напряжение": "24 В",
    }


SECTIONS = """
<div id="specifications"><table>
  <tr><td>Вес</td><td>168 г</td></tr>
  <tr><td colspan="2">Сенсор влажности</td></tr>
  <tr><td>Диапазон измерений</td><td>10… 95 %</td></tr>
  <tr><td colspan="2">Сенсор температуры</td></tr>
  <tr><td>Диапазон измерений</td><td>0 … +50 °C</td></tr>
</table></div>
"""


SHIFTED = """
<div id="specifications"><table>
  <tr><td colspan="9">Ёмкость</td></tr>
  <tr><td colspan="2">Диапазон</td><td colspan="3">Разрешение</td><td colspan="3">Точность</td><td>Импеданс</td></tr>
  <tr><td colspan="4">1000 мкФ</td><td colspan="3">0,1 мкФ</td><td colspan="2">± 3%</td></tr>
  <tr><td colspan="5">Параметр</td><td colspan="4">Значение</td></tr>
  <tr><td colspan="5">Питание</td><td colspan="4">Батарея 9В</td></tr>
</table></div>
"""


def test_misaligned_columns_mapped_by_order():
    specs = parse_specs(BeautifulSoup(SHIFTED, "html.parser"))
    assert specs == {
        "Ёмкость: Диапазон 1000 мкФ": "Разрешение: 0,1 мкФ; Точность: ± 3%",
        "Питание": "Батарея 9В",
    }


def test_same_key_in_different_sections_kept():
    specs = parse_specs(BeautifulSoup(SECTIONS, "html.parser"))
    assert specs == {
        "Вес": "168 г",
        "Сенсор влажности: Диапазон измерений": "10… 95 %",
        "Сенсор температуры: Диапазон измерений": "0 … +50 °C",
    }


def test_parse_description_skips_tables():
    text = parse_description(BeautifulSoup(PAGE, "html.parser"))
    assert text == "Преобразователь давления для сложных условий.\nЗащита от гидроударов"


VARIANTS = """
<div id="specifications"><table>
  <tr><td>Типоразмер</td><td>MINI</td><td>MIDI</td><td>MAXI</td></tr>
  <tr><td>Тип выхода</td><td>реле</td><td>транзистор</td><td>реле</td></tr>
  <tr><td>Ток, А</td><td>1</td><td>2</td><td>3</td></tr>
</table></div>
"""


def test_digitless_data_row_is_not_header():
    specs = parse_specs(BeautifulSoup(VARIANTS, "html.parser"))
    assert specs == {
        "Тип выхода": "MINI: реле; MIDI: транзистор; MAXI: реле",
        "Ток, А": "MINI: 1; MIDI: 2; MAXI: 3",
    }
