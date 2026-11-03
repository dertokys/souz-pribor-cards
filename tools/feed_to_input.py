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
        with path.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)


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
        parts.extend(clean(line) for line in block.get_text("").split("\n"))
    return "; ".join(p for p in parts if p)


def parse_specs(soup: BeautifulSoup) -> dict[str, str]:
    specs: dict[str, str] = {}
    block = soup.find(id="specifications")
    if block:
        last_key = None
        for row in block.find_all("tr"):
            cells = [cell_text(td) for td in row.find_all(["td", "th"])]
            if len(cells) != 2:
                continue
            key, value = cells
            key = key.rstrip(":")
            if last_key and value and (not key or key[0].islower()):
                merged_key = f"{last_key} {key}".strip()
                specs[merged_key] = f"{specs.pop(last_key)} {value}"
                last_key = merged_key
                continue
            if not key or not value or key.lower() in SKIP_SPEC_KEYS:
                continue
            specs[key] = value
            last_key = key
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
