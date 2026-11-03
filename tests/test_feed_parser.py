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


def test_parse_description_skips_tables():
    text = parse_description(BeautifulSoup(PAGE, "html.parser"))
    assert text == "Преобразователь давления для сложных условий.\nЗащита от гидроударов"
