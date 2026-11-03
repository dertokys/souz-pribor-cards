import re
from dataclasses import dataclass, field

from .prompts import DESCRIPTION_MAX, DESCRIPTION_MIN, QUERIES_MAX, QUERIES_MIN, TITLE_MAX
from .schemas import NO_DATA, LLMCard, ProductInput, SpecLine

_LOOKALIKES = str.maketrans({
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t", "у": "y", "х": "x",
    "×": "x", "–": "-", "—": "-", "−": "-", "℃": "°c", "\xa0": " ", "ё": "е",
})
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_THOUSANDS_RE = re.compile(r"(?<=\d)[ \xa0](?=\d{3}(?!\d))")
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+(?=[А-ЯЁA-Z0-9«\"])")


_LATIN_TO_CYRILLIC = str.maketrans("aeopcxyAEOPCXBKMHT", "аеорсхуАЕОРСХВКМНТ")
_MIXED_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+")


def fix_mixed_script(text: str) -> str:
    def fix(match: re.Match) -> str:
        word = match.group(0)
        cyrillic = sum("а" <= ch.lower() <= "я" or ch in "ёЁ" for ch in word)
        if 0 < cyrillic < len(word) and cyrillic * 2 > len(word):
            return word.translate(_LATIN_TO_CYRILLIC)
        return word

    text = text.replace("‐", "-").replace("‑", "-").replace("\xa0", " ")
    return _MIXED_WORD_RE.sub(fix, text)


def norm(text: str) -> str:
    text = text.lower().translate(_LOOKALIKES).replace("…", "...")
    text = re.sub(r"(?<=\d),(?=\d)", ".", text)
    return re.sub(r"\s+", "", text)


def _canon_number(raw: str) -> str:
    whole, _, fraction = raw.replace(",", ".").partition(".")
    whole = whole.lstrip("0") or "0"
    fraction = fraction.rstrip("0")
    return f"{whole}.{fraction}" if fraction else whole


def numbers(text: str) -> set[str]:
    joined = _THOUSANDS_RE.sub("", text)
    return {_canon_number(n) for n in _NUMBER_RE.findall(text) + _NUMBER_RE.findall(joined)}


def source_numbers(product: ProductInput) -> set[str]:
    parts = [product.name, product.manufacturer, product.product_type, product.category, product.description]
    for key, value in product.specs.items():
        parts.extend([key, value])
    return numbers(" ".join(parts))


def ungrounded_numbers(text: str, allowed: set[str]) -> list[str]:
    joined = _THOUSANDS_RE.sub("", text)
    found = [_canon_number(n) for n in _NUMBER_RE.findall(joined)]
    return sorted({n for n in found if n not in allowed}, key=lambda n: (len(n), n))


def split_paragraphs(text: str) -> list[list[str]]:
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n|\n", text):
        sentences = [s.strip() for s in _SENTENCE_RE.split(paragraph.strip()) if s.strip()]
        if sentences:
            paragraphs.append(sentences)
    return paragraphs


@dataclass
class Report:
    issues: list[str] = field(default_factory=list)
    spec_lines: list[SpecLine] = field(default_factory=list)
    spec_warnings: list[str] = field(default_factory=list)


def _find_spec_key(source_key: str, specs: dict[str, str]) -> str | None:
    if source_key in specs:
        return source_key
    target = norm(source_key)
    return next((k for k in specs if norm(k) == target), None)


IDENTITY_FIELDS = {
    "производитель", "бренд", "марка", "модель", "название", "наименование",
    "артикул", "тип", "тип прибора", "тип устройства", "категория",
}
_PLACEHOLDER_NAME_RE = re.compile(r"^(данные|нет данных)|отсутствующ|типовой параметр", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-zа-яё]{3,}", re.IGNORECASE)


def stems(text: str) -> set[str]:
    return {w.lower().translate(_LOOKALIKES)[:4] for w in _WORD_RE.findall(text)}


def supported_by_text(value: str, text: str) -> bool:
    if not value.strip() or not text.strip():
        return False
    if any(n not in numbers(text) for n in numbers(value)):
        return False
    if norm(value) in norm(text):
        return True
    value_stems = stems(value)
    return bool(value_stems) and len(value_stems & stems(text)) / len(value_stems) >= 0.75


_DESCRIPTION_PAIR_RE = re.compile(r"^\s*([^:\n]{3,80}):\s*(.+?)\s*$", re.MULTILINE)


def find_conflicts(product: ProductInput) -> list[str]:
    conflicts = []
    for key, desc_value in _DESCRIPTION_PAIR_RE.findall(product.description):
        spec_key = next((k for k in product.specs if norm(k) == norm(key)), None)
        if spec_key is None:
            continue
        spec_value = product.specs[spec_key]
        if numbers(spec_value) != numbers(desc_value):
            conflicts.append(f"{spec_key}: в характеристиках «{spec_value}», в описании «{desc_value.rstrip('.')}»")
    return conflicts


def check_specs(card: LLMCard, product: ProductInput, report: Report) -> None:
    source_text = "\n".join(t for t in [product.product_type, product.description] if t)
    seen: set[str] = set()

    for spec in card.key_specs:
        source = spec.source.strip()
        name = spec.name.strip()
        if not name or name.lower() in {"none", NO_DATA} or _PLACEHOLDER_NAME_RE.search(name):
            continue
        name = name[:1].upper() + name[1:]
        if name.lower() in IDENTITY_FIELDS:
            report.issues.append(f"key_specs «{name}»: это не техническая характеристика, убери её из key_specs")
            continue

        if source.lower() == "none":
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            if _find_spec_key(name, product.specs):
                report.issues.append(f"key_specs «{name}»: помечено «{NO_DATA}», но такая характеристика есть в specs")
            report.spec_lines.append(SpecLine(name=name, value=NO_DATA, source="none", status="no_data"))
            continue

        if source.lower().startswith("specs:"):
            key = _find_spec_key(source[6:].strip(), product.specs)
            if key is None:
                report.issues.append(f"key_specs «{name}»: источник «{source}» не найден в specs")
                continue
            if key in seen:
                continue
            seen.add(key)
            original = product.specs[key]
            status = "ok"
            if norm(spec.value) not in norm(original):
                status = "corrected"
                report.spec_warnings.append(
                    f"Характеристика «{name}»: модель вернула «{spec.value}», заменено на исходное «{original}»"
                )
            report.spec_lines.append(SpecLine(name=name, value=original, source=f"specs:{key}", status=status))
            continue

        if source.lower() in {"text", "description"}:
            value = spec.value.strip()
            if not supported_by_text(value, source_text):
                report.issues.append(
                    f"key_specs «{name}»: значение «{value}» не найдено в описании или типе товара — "
                    f"возьми дословный фрагмент или поставь source \"none\""
                )
                continue
            report.spec_lines.append(SpecLine(name=name, value=value, source="text", status="from_text"))
            continue

        report.issues.append(f"key_specs «{name}»: недопустимый source «{source}» (нужно specs:<ключ>, text или none)")


def check_texts(card: LLMCard, product: ProductInput, report: Report) -> None:
    allowed = source_numbers(product)
    fields = {
        "seo_title": card.seo_title,
        "seo_description": card.seo_description,
        "commercial.summary": card.commercial.summary,
    }
    fields.update({f"commercial.target_customers[{i}]": t for i, t in enumerate(card.commercial.target_customers)})
    fields.update({f"commercial.tasks[{i}]": t for i, t in enumerate(card.commercial.tasks)})
    fields.update({f"search_queries[{i}]": q for i, q in enumerate(card.search_queries)})

    for name, text in fields.items():
        bad = ungrounded_numbers(text, allowed)
        if bad:
            report.issues.append(f"{name}: числа {', '.join(bad)} отсутствуют во входных данных — убери их")


def check_format(card: LLMCard, report: Report) -> None:
    title_len = len(card.seo_title.strip())
    if not title_len:
        report.issues.append("seo_title пустой")
    elif title_len > TITLE_MAX:
        report.issues.append(f"seo_title: {title_len} символов, нужно не больше {TITLE_MAX}")

    desc_len = len(card.seo_description.strip())
    if not DESCRIPTION_MIN <= desc_len <= DESCRIPTION_MAX:
        report.issues.append(f"seo_description: {desc_len} символов, нужно {DESCRIPTION_MIN}–{DESCRIPTION_MAX}")

    queries = [q for q in card.search_queries if q.strip()]
    if not QUERIES_MIN <= len(queries) <= QUERIES_MAX:
        report.issues.append(f"search_queries: {len(queries)} шт., нужно {QUERIES_MIN}–{QUERIES_MAX}")

    if not card.commercial.summary.strip():
        report.issues.append("commercial.summary пустой")
    if not card.commercial.target_customers:
        report.issues.append("commercial.target_customers пустой")
    if not card.commercial.tasks:
        report.issues.append("commercial.tasks пустой")


def validate(card: LLMCard, product: ProductInput) -> Report:
    report = Report()
    check_format(card, report)
    check_specs(card, product, report)
    check_texts(card, product, report)
    return report
