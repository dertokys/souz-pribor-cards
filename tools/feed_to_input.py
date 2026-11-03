import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

FEED_URL = "https://www.souz-pribor.ru/yml/any/feed.xml"
USER_AGENT = "Mozilla/5.0 (souz-pribor-cards test task)"
DESCRIPTION_LIMIT = 3000
SKIP_SPEC_KEYS = {"наименование", "параметр", "характеристика", "артикул"}


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def download_feed(path: Path) -> None:
    with httpx.stream("GET", FEED_URL, headers={"User-Agent": USER_AGENT}, timeout=120, follow_redirects=True) as r:
        r.raise_for_status()
        partial = path.with_name(path.name + ".part")
        with partial.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    partial.replace(path)


def find_offer(feed_path: Path, offer_id: str) -> tuple[dict, dict]:
    categories: dict[str, str] = {}
    for _, el in ET.iterparse(feed_path, events=("end",)):
        if el.tag == "category":
            categories[el.get("id")] = clean(el.text or "")
        elif el.tag == "offer":
            if el.get("id") == offer_id:
                offer = {child.tag: clean(child.text or "") for child in el if child.tag != "param"}
                offer["params"] = {p.get("name"): clean(p.text or "") for p in el.findall("param")}
                return offer, categories
            el.clear()
    raise SystemExit(f"Оффер {offer_id} не найден в фиде")


def cell_text(cell) -> str:
    for br in cell.find_all("br"):
        br.replace_with("\n")
    blocks = cell.find_all(["p", "li"]) or [cell]
    parts = []
    for block in blocks:
        parts.extend(clean(line).strip(" ,;") for line in block.get_text("").split("\n"))
    return "; ".join(p for p in parts if p)


def _span(cell, name: str) -> int:
    try:
        return max(1, int(cell.get(name) or 1))
    except ValueError:
        return 1


Cell = tuple[int, int, str]


def table_grid(table) -> list[tuple[list[str], list[Cell]]]:
    grid = []
    pending: dict[int, list] = {}
    for tr in table.find_all("tr"):
        cells = iter(tr.find_all(["td", "th"]))
        row: list[str] = []
        spans: list[Cell] = []
        col = 0
        while True:
            if col in pending:
                text, left = pending[col]
                row.append(text)
                spans.append((col, col + 1, text))
                if left <= 1:
                    del pending[col]
                else:
                    pending[col][1] = left - 1
                col += 1
                continue
            cell = next(cells, None)
            if cell is None:
                break
            text = cell_text(cell)
            rowspan = _span(cell, "rowspan")
            width = _span(cell, "colspan")
            spans.append((col, col + width, text))
            for _ in range(width):
                if rowspan > 1:
                    pending[col] = [text, rowspan - 1]
                row.append(text)
                col += 1
        grid.append((row, spans))
    return grid


def _is_subitem(key: str) -> bool:
    return bool(key) and (key[0] in "-–—•" or key[0].isdigit())


def _unique(values) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _aligned(header_cells: list[Cell], row_cells: list[Cell]) -> bool:
    starts = {s for s, _, _ in header_cells}
    ends = {e for _, e, _ in header_cells}
    for s, e, _ in row_cells:
        inside = any(hs <= s and e <= he for hs, he, _ in header_cells)
        if not inside and not (s in starts and e in ends):
            return False
    return True


def _format_groups(groups: dict[str, list[str]]) -> str:
    groups = {label: _unique(values) for label, values in groups.items()}
    groups = {label: values for label, values in groups.items() if values}
    if len(groups) == 1:
        return ", ".join(next(iter(groups.values())))
    return "; ".join(f"{label}: {', '.join(values)}" if label else ", ".join(values) for label, values in groups.items())


def _matrix_value(header: tuple[list[str], list[Cell]], row: tuple[list[str], list[Cell]]) -> str:
    (header_values, header_cells), (row_values, row_cells) = header, row
    groups: dict[str, list[str]] = {}
    if _aligned(header_cells, row_cells):
        for label, value in zip(header_values[1:], row_values[1:]):
            if label != header_values[0]:
                groups.setdefault(label, []).append(value)
    else:
        labels = [text for _, _, text in header_cells]
        values = [text for _, _, text in row_cells]
        for label, value in zip(labels[1:], values[1:]):
            groups.setdefault(label, []).append(value)
    return _format_groups(groups)


def parse_table(table, specs: dict[str, str], key_sections: dict[str, str]) -> None:
    section = ""
    group = ""
    header: tuple[list[str], list[Cell]] | None = None
    last_key = None
    just_sectioned = False
    for grid_row in table_grid(table):
        row = grid_row[0]
        if not any(row):
            continue
        if len(set(row)) == 1:
            section, group, last_key = row[0].rstrip(":"), "", None
            just_sectioned = True
            continue

        first, rest = row[0], row[1:]
        if len(set(rest)) > 1:
            if not any(ch.isdigit() for c in row for ch in c):
                header = grid_row
                if not just_sectioned:
                    section = ""
                just_sectioned = False
                continue
            just_sectioned = False
            if header and len(header[0]) == len(row):
                key = f"{header[0][0]} {first}" if any(ch.isdigit() for ch in first) else first
                value = _matrix_value(header, grid_row)
            else:
                key, value = first, "; ".join(_unique(rest))
            if section:
                key = f"{section}: {key}"
            if key and value:
                specs.setdefault(key, value)
            continue

        just_sectioned = False
        key, value = first, (rest[0] if rest else "")
        key = key.rstrip(":")
        if key and not value:
            group, last_key = key, None
            continue
        if key and value and (_is_subitem(key) or (group and key[0].islower())):
            context = group or section
            key = f"{context} — {key.lstrip('-–—• ')}" if context else key
            specs.setdefault(key, value)
            continue
        group = ""
        if last_key and value and (not key or key[0].islower()):
            merged_key = f"{last_key} {key}".strip()
            specs[merged_key] = f"{specs.pop(last_key)} {value}"
            last_key = merged_key
            continue
        if not key or not value or key.lower() in SKIP_SPEC_KEYS:
            last_key = None
            continue
        if key in specs:
            first_section = key_sections.get(key, "")
            if not section or section == first_section:
                last_key = None
                continue
            if first_section:
                specs[f"{first_section}: {key}"] = specs.pop(key)
            key = f"{section}: {key}"
        specs[key] = value
        key_sections[key] = section
        last_key = key


def parse_specs(soup: BeautifulSoup) -> dict[str, str]:
    specs: dict[str, str] = {}
    key_sections: dict[str, str] = {}
    block = soup.find(id="specifications")
    if block:
        for table in block.find_all("table"):
            parse_table(table, specs, key_sections)
    for item in soup.select(".characteristics__item"):
        name = item.select_one(".characteristics__name")
        desc = item.select_one(".characteristics__desc")
        if name and desc:
            key = clean(name.get_text(" ")).rstrip(":")
            if key.lower() in SKIP_SPEC_KEYS:
                continue
            specs.setdefault(key, clean(desc.get_text(" ")).replace(" ,", ","))
    return specs


def parse_description(soup: BeautifulSoup) -> str:
    block = soup.select_one("#description .product-description") or soup.find(id="description")
    if not block:
        return ""
    for tag in block.find_all(["table", "img", "picture", "script", "style"]):
        tag.decompose()
    lines = []
    for el in block.find_all(["p", "li", "h2", "h3"]):
        text = clean(el.get_text(" "))
        if text and text not in lines:
            lines.append(text)
    text = "\n".join(lines)
    if len(text) > DESCRIPTION_LIMIT:
        text = text[:DESCRIPTION_LIMIT].rsplit(" ", 1)[0] + "…"
    return text


def fetch_page(url: str) -> BeautifulSoup:
    r = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def build_input(offer: dict, categories: dict, soup: BeautifulSoup | None) -> dict:
    data = {
        "name": offer.get("name", ""),
        "manufacturer": offer.get("vendor", ""),
        "product_type": offer.get("typePrefix", ""),
        "category": categories.get(offer.get("categoryId", ""), ""),
        "sku": offer.get("vendorCode", ""),
        "url": offer.get("url", ""),
        "specs": {},
        "description": "",
    }
    if soup is not None:
        data["specs"] = parse_specs(soup)
        data["description"] = parse_description(soup)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Собрать входной JSON товара из YML-фида souz-pribor.ru")
    parser.add_argument("offer_id", help="id оффера в фиде")
    parser.add_argument("-o", "--out", type=Path, help="куда сохранить JSON (по умолчанию stdout)")
    parser.add_argument("--feed", type=Path, default=Path(".cache/feed.xml"), help="локальная копия фида")
    parser.add_argument("--no-page", action="store_true", help="только данные фида, без страницы товара")
    args = parser.parse_args()

    if not args.feed.exists():
        args.feed.parent.mkdir(parents=True, exist_ok=True)
        print(f"Скачиваю фид в {args.feed}…", file=sys.stderr)
        download_feed(args.feed)

    offer, categories = find_offer(args.feed, args.offer_id)
    soup = None if args.no_page else fetch_page(offer["url"])
    data = build_input(offer, categories, soup)

    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"Сохранено: {args.out} (характеристик: {len(data['specs'])})", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
