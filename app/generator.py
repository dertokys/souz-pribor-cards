import json
from datetime import datetime, timezone

from pydantic import ValidationError

from .llm import LLMBadResponse, LLMClient, LLMError
from .prompts import (
    DESCRIPTION_MAX,
    DESCRIPTION_MIN,
    QUERIES_MAX,
    QUERIES_MIN,
    SYSTEM_PROMPT,
    TITLE_MAX,
    build_repair_prompt,
    build_user_prompt,
)
from .schemas import CardResult, Commercial, LLMCard, MissingField, ProductInput, ProductRef, Quality
from .validator import (
    NumberCheck,
    Report,
    find_conflicts,
    fix_mixed_script,
    mixed_script_words,
    norm,
    split_paragraphs,
    validate,
)


def parse_card(raw: str) -> LLMCard:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        start = text.find("{")
        text = text[start:] if start >= 0 else text
    try:
        return LLMCard.model_validate(json.loads(text))
    except json.JSONDecodeError as e:
        raise LLMBadResponse(f"ответ не является JSON ({e.msg})") from e
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()[:5])
        raise LLMBadResponse(f"JSON не соответствует схеме ({problems})") from e


def _fix_strings(value):
    if isinstance(value, str):
        return fix_mixed_script(value)
    if isinstance(value, list):
        return [_fix_strings(v) for v in value]
    if isinstance(value, dict):
        return {k: _fix_strings(v) for k, v in value.items()}
    return value


def issue_kind(issue: str) -> str:
    return issue.split(":", 1)[0]


def cut_to_words(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    head = text[: limit + 1]
    cut = head.rsplit(" ", 1)[0] if " " in head else text[:limit]
    return cut.rstrip(" ,;:-–—")


def fallback_title(product: ProductInput) -> str:
    parts = [product.product_type, product.manufacturer, product.name]
    title = " ".join(p for p in parts if p)
    title = title[:1].upper() + title[1:]
    if len(title) > TITLE_MAX:
        title = " ".join(p for p in [product.manufacturer, product.name] if p)
    return cut_to_words(title, TITLE_MAX)


def drop_ungrounded_sentences(text: str, check: NumberCheck, field: str, warnings: list[str]) -> str:
    paragraphs = []
    for sentences in split_paragraphs(text):
        kept = []
        for sentence in sentences:
            bad = check(sentence)
            if bad:
                warnings.append(f"{field}: удалено предложение с неподтверждёнными числами ({', '.join(bad)}): «{sentence}»")
            else:
                kept.append(sentence)
        if kept:
            paragraphs.append(" ".join(kept))
    return "\n\n".join(paragraphs)


def trim_to_length(text: str, limit: int) -> str:
    paragraphs = split_paragraphs(text)
    while paragraphs and len("\n\n".join(" ".join(p) for p in paragraphs)) > limit:
        paragraphs[-1].pop()
        if not paragraphs[-1]:
            paragraphs.pop()
    return "\n\n".join(" ".join(p) for p in paragraphs)


def drop_ungrounded_items(items: list[str], check: NumberCheck, field: str, warnings: list[str]) -> list[str]:
    kept = []
    for item in items:
        item = item.strip()
        if not item:
            continue
        bad = check(item)
        if bad:
            warnings.append(f"{field}: удалён пункт с неподтверждёнными числами ({', '.join(bad)}): «{item}»")
        else:
            kept.append(item)
    return kept


def finalize(
    card: LLMCard,
    report: Report,
    product: ProductInput,
    missing: list[MissingField],
    attempts: int,
    model: str,
    repaired_issues: list[str],
    notes: list[str] | None = None,
) -> CardResult:
    check = NumberCheck(product)
    warnings = list(notes or []) + list(report.spec_warnings)
    card = LLMCard.model_validate(_fix_strings(card.model_dump()))

    title = " ".join(card.seo_title.split())
    title = title[:1].upper() + title[1:]
    if check(title):
        warnings.append(f"seo_title содержал неподтверждённые числа и заменён шаблонным: «{title}»")
        title = fallback_title(product)
    elif len(title) > TITLE_MAX:
        warnings.append(f"seo_title был длиннее {TITLE_MAX} символов и обрезан по словам")
        title = cut_to_words(title, TITLE_MAX)

    description = drop_ungrounded_sentences(card.seo_description.strip(), check, "seo_description", warnings)
    if len(description) > DESCRIPTION_MAX:
        trimmed = trim_to_length(description, DESCRIPTION_MAX)
        if len(trimmed) >= DESCRIPTION_MIN:
            warnings.append(f"seo_description: {len(description)} символов — убраны последние предложения до {len(trimmed)}")
            description = trimmed
    if not DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX:
        warnings.append(f"seo_description: {len(description)} символов вместо {DESCRIPTION_MIN}–{DESCRIPTION_MAX}")

    queries = drop_ungrounded_items(card.search_queries, check, "search_queries", warnings)[:QUERIES_MAX]
    if len(queries) < QUERIES_MIN:
        warnings.append(f"search_queries: осталось {len(queries)} шт. вместо {QUERIES_MIN}–{QUERIES_MAX}")

    commercial = Commercial(
        summary=drop_ungrounded_sentences(card.commercial.summary.strip(), check, "commercial.summary", warnings),
        target_customers=drop_ungrounded_items(card.commercial.target_customers, check, "commercial.target_customers", warnings),
        tasks=drop_ungrounded_items(card.commercial.tasks, check, "commercial.tasks", warnings),
    )

    texts = [title, description, commercial.summary, *queries, *commercial.target_customers, *commercial.tasks]
    for word in mixed_script_words(" ".join(texts)):
        warnings.append(f"Слово «{word}» содержит буквы разных алфавитов — проверьте написание")

    for issue in report.issues:
        if issue.startswith("key_specs"):
            warnings.append(f"Отброшено при проверке: {issue}")

    missing = list(missing)
    known = {norm(m.field.removeprefix("specs.")) for m in missing}
    for spec in report.spec_lines:
        if spec.status == "no_data" and norm(spec.name) not in known:
            known.add(norm(spec.name))
            missing.append(MissingField(field=spec.name, reason="важный для выбора параметр отсутствует во входных данных"))

    conflicts = [c.text for c in find_conflicts(product)]
    found_keys = [norm(issue_kind(c)) for c in conflicts]
    if product.specs and product.description:
        for conflict in card.data_conflicts:
            conflict = conflict.strip()
            if conflict and not any(k and k in norm(conflict) for k in found_keys):
                conflicts.append(conflict)

    return CardResult(
        product=ProductRef(name=product.name, manufacturer=product.manufacturer, sku=product.sku, url=product.url),
        seo_title=title,
        seo_description=description,
        key_specs=report.spec_lines,
        search_queries=queries,
        commercial=commercial,
        missing_fields=missing,
        data_conflicts=conflicts,
        quality=Quality(
            needs_review=bool(warnings or conflicts),
            attempts=attempts,
            seo_title_length=len(title),
            seo_description_length=len(description),
            warnings=warnings,
            repaired_issues=repaired_issues,
        ),
        model=model,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


class CardGenerator:
    def __init__(self, llm: LLMClient, max_attempts: int = 2):
        self.llm = llm
        self.max_attempts = max_attempts

    def generate(self, product: ProductInput, missing: list[MissingField]) -> CardResult:
        check = NumberCheck(product)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(product, json_hint=not self.llm.structured_outputs)},
        ]
        best: tuple[LLMCard, Report] | None = None
        last_error: LLMBadResponse | None = None
        attempts = 0
        sent_for_repair: list[str] = []
        notes: list[str] = []

        for attempt in range(1, self.max_attempts + 1):
            try:
                raw = self.llm.complete(messages)
            except LLMError as e:
                if best is None:
                    raise
                notes.append(f"Повторный запрос к модели не выполнен ({e.message}) — использован предыдущий ответ")
                break
            attempts = attempt
            try:
                card = parse_card(raw)
            except LLMBadResponse as e:
                last_error = e
                issues = [f"Ответ не разобран: {e.message}"]
            else:
                report = validate(card, product, check)
                if best is None or len(report.issues) <= len(best[1].issues):
                    best = (card, report)
                if not report.issues:
                    break
                issues = report.issues
            if attempt < self.max_attempts:
                sent_for_repair.extend(issues)
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": build_repair_prompt(issues)})

        if best is None:
            raise LLMBadResponse(f"Модель не вернула корректный JSON за {attempts} попыт(ки): {last_error.message if last_error else ''}")

        card, report = best
        remaining = {issue_kind(i) for i in report.issues}
        repaired = [i for i in sent_for_repair if issue_kind(i) not in remaining]
        return finalize(card, report, product, missing, attempts, self.llm.model, repaired, notes)
