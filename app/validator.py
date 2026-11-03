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
_TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+(?:[-.,/×][0-9A-Za-zА-Яа-яЁё]+)*")
_LETTER_RE = re.compile(r"[A-Za-zА-Яа-яЁё]")
_LATIN_TO_CYRILLIC = str.maketrans("aeopcxymkAEOPCXBKMHT", "аеорсхумкАЕОРСХВКМНТ")
_CYRILLIC_TO_LATIN = str.maketrans("аеорсхумкАЕОРСХВКМНТ", "aeopcxymkAEOPCXBKMHT")
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+")
_STEM_RE = re.compile(r"[a-zа-яё]{3,}", re.IGNORECASE)
_DESCRIPTION_PAIR_RE = re.compile(r"^\s*([^:\n]{3,80}):\s*(.+?)\s*$", re.MULTILINE)

_IDENTITY_RE = re.compile(
    r"^(производитель|бренд|марка|модель|название|наименование|артикул|категория|"
    r"тип( прибора| устройства| изделия| товара)?$|"
    r"гаранти|цена|стоимость|срок поставки|наличие на складе|доставка)",
    re.IGNORECASE,
)
_NO_DATA_PREFIX_RE = re.compile(r"^\s*(данных нет|нет данных)\s*[—–:\-]\s*", re.IGNORECASE)
NOT_A_SPEC = "это не техническая характеристика"
_META_NOTE_RE = re.compile(r"\s*\([^)]*(обычно|важн|типов|уточн|полный|в описании)[^)]*\)", re.IGNORECASE)
_PLACEHOLDER_NAME_RE = re.compile(
    r"^(данные|нет данных|остальн|прочие|другие|иные)|отсутствующ|типовой параметр", re.IGNORECASE
)


def _is_cyrillic(ch: str) -> bool:
    return "а" <= ch.lower() <= "я" or ch in "ёЁ"


def _fix_word(word: str) -> str:
    cyrillic = sum(_is_cyrillic(ch) for ch in word)
    if cyrillic in (0, len(word)):
        return word
    if cyrillic * 2 >= len(word):
        return word.translate(_LATIN_TO_CYRILLIC)
    return word.translate(_CYRILLIC_TO_LATIN)


def source_words(*texts: str) -> set[str]:
    return {w.lower() for text in texts for w in _WORD_RE.findall(text)}


def fix_mixed_script(text: str, keep: set[str] = frozenset()) -> str:
    text = text.replace("‐", "-").replace("‑", "-").replace("\xa0", " ")
    return _WORD_RE.sub(lambda m: m.group(0) if m.group(0).lower() in keep else _fix_word(m.group(0)), text)


def mixed_script_words(text: str, keep: set[str] = frozenset()) -> list[str]:
    result = []
    for word in _WORD_RE.findall(text):
        cyrillic = sum(_is_cyrillic(ch) for ch in word)
        if 0 < cyrillic < len(word) and word.lower() not in keep and word not in result:
            result.append(word)
    return result


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


@dataclass
class Conflict:
    key: str
    spec_value: str
    description_value: str
    line: str

    @property
    def text(self) -> str:
        return f"{self.key}: в характеристиках «{self.spec_value}», в описании «{self.description_value.rstrip('.')}»"


def find_conflicts(product: ProductInput) -> list[Conflict]:
    conflicts = []
    for match in _DESCRIPTION_PAIR_RE.finditer(product.description):
        key, desc_value = match.group(1), match.group(2)
        spec_key = next((k for k in product.specs if norm(k) == norm(key)), None)
        if spec_key is None:
            continue
        spec_value = product.specs[spec_key]
        desc_numbers = numbers(desc_value)
        if desc_numbers and not desc_numbers <= numbers(spec_value):
            conflicts.append(Conflict(spec_key, spec_value, desc_value, match.group(0)))
    return conflicts


class NumberCheck:
    def __init__(self, product: ProductInput):
        self.identifiers = [product.name.lower().translate(_LOOKALIKES)] if product.name else []
        description = product.description
        for conflict in find_conflicts(product):
            description = description.replace(conflict.line, " ")
        parts = [product.manufacturer, product.product_type, product.category, description]
        for key, value in product.specs.items():
            parts.extend([key, value])
        self.allowed = numbers(self.strip_identifiers(" ".join(parts)))

    def strip_identifiers(self, text: str) -> str:
        def replace(match: re.Match) -> str:
            token = match.group(0)
            if _LETTER_RE.search(token) and any(ch.isdigit() for ch in token):
                key = token.lower().translate(_LOOKALIKES)
                if any(key in identifier for identifier in self.identifiers):
                    return " "
            return token

        return _TOKEN_RE.sub(replace, text)

    def __call__(self, text: str) -> list[str]:
        found = {_canon_number(n) for n in _NUMBER_RE.findall(self.strip_identifiers(text))}
        return sorted((n for n in found if n not in self.allowed), key=lambda n: (len(n), n))


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


def _base_key(key: str) -> str:
    return norm(re.sub(r"\(.*?\)", "", key).split(",")[0])


def _find_spec_key(source_key: str, specs: dict[str, str]) -> str | None:
    if source_key in specs:
        return source_key
    target = norm(source_key)
    exact = next((k for k in specs if norm(k) == target), None)
    if exact is not None:
        return exact
    base = _base_key(source_key)
    matches = [k for k in specs if base and _base_key(k) == base]
    return matches[0] if len(matches) == 1 else None


def stems(text: str) -> set[str]:
    return {w.lower().translate(_LOOKALIKES)[:4] for w in _STEM_RE.findall(text)}


def supported_by_text(value: str, text: str) -> bool:
    if not value.strip() or not text.strip():
        return False
    text_numbers = numbers(text)
    if any(n not in text_numbers for n in numbers(value)):
        return False
    if norm(value) in norm(text):
        return True
    value_stems = stems(value)
    return bool(value_stems) and len(value_stems & stems(text)) / len(value_stems) >= 0.75


def _spec_line(name: str, key: str, value: str, status: str) -> SpecLine:
    short, full = (re.sub(r"[\W_]", "", norm(x)) for x in (name, key))
    display = key if status == "corrected" or (short != full and (short in full or "," in key)) else name
    return SpecLine(name=display, value=value, source=f"specs:{key}", status=status)


def check_specs(card: LLMCard, product: ProductInput, report: Report) -> None:
    source_text = "\n".join(t for t in [product.product_type, product.description] if t)
    seen: set[str] = set()

    for spec in card.key_specs:
        source = spec.source.strip()
        name = _NO_DATA_PREFIX_RE.sub("", _META_NOTE_RE.sub("", spec.name)).strip()
        if not name or name.lower() in {"none", NO_DATA} or _PLACEHOLDER_NAME_RE.search(name):
            continue
        name = name[:1].upper() + name[1:]
        if _IDENTITY_RE.match(name):
            report.issues.append(f"key_specs «{name}»: {NOT_A_SPEC}, убери её из key_specs")
            continue

        if source.lower() == "none":
            key = _find_spec_key(name, product.specs)
            if key is not None:
                if key not in seen:
                    seen.add(key)
                    report.spec_lines.append(_spec_line(name, key, product.specs[key], "corrected"))
                    report.spec_warnings.append(
                        f"Характеристика «{name}»: модель пометила «{NO_DATA}», подставлено значение из входных данных"
                    )
                continue
            if name.lower() not in seen:
                seen.add(name.lower())
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
            report.spec_lines.append(_spec_line(name, key, original, status))
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


def check_texts(card: LLMCard, check: NumberCheck, report: Report) -> None:
    fields = {
        "seo_title": card.seo_title,
        "seo_description": card.seo_description,
        "commercial.summary": card.commercial.summary,
    }
    fields.update({f"commercial.target_customers[{i}]": t for i, t in enumerate(card.commercial.target_customers)})
    fields.update({f"commercial.tasks[{i}]": t for i, t in enumerate(card.commercial.tasks)})
    fields.update({f"search_queries[{i}]": q for i, q in enumerate(card.search_queries)})

    for name, text in fields.items():
        bad = check(text)
        if bad:
            report.issues.append(
                f"{name}: числа {', '.join(bad)} не подтверждаются входными данными "
                f"(числа из маркировки модели и из противоречащих строк описания не считаются) — убери их"
            )


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


def validate(card: LLMCard, product: ProductInput, check: NumberCheck | None = None) -> Report:
    report = Report()
    check_format(card, report)
    check_specs(card, product, report)
    check_texts(card, check or NumberCheck(product), report)
    return report
