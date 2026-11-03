from .schemas import CardResult

STATUS_LABELS = {
    "ok": "",
    "corrected": "исправлено по входным данным",
    "from_text": "из описания — проверить",
    "no_data": "уточнить у поставщика",
}


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def review_reason(card: CardResult) -> str:
    reasons = []
    if card.data_conflicts:
        reasons.append(f"противоречия во входных данных ({len(card.data_conflicts)})")
    if card.quality.warnings:
        reasons.append(f"автоматические правки ({len(card.quality.warnings)}), см. раздел «Проверка»")
    return "; ".join(reasons)


def to_markdown(card: CardResult) -> str:
    p = card.product
    title = p.name if p.manufacturer.lower() in p.name.lower() else " ".join(x for x in [p.manufacturer, p.name] if x)
    lines = [f"# Черновик карточки: {title}", ""]
    meta = [f"Артикул: {p.sku}" if p.sku else "", f"[страница товара]({p.url})" if p.url else ""]
    meta = [m for m in meta if m]
    if meta:
        lines += [" · ".join(meta), ""]

    if card.quality.needs_review:
        lines += [f"> **Требует проверки:** {review_reason(card)}.", ""]

    lines += [
        f"## SEO-заголовок ({card.quality.seo_title_length} симв.)",
        "",
        "```text",
        card.seo_title,
        "```",
        "",
        f"## SEO-описание ({card.quality.seo_description_length} симв.)",
        "",
        "```text",
        card.seo_description,
        "```",
        "",
        "## Ключевые характеристики",
        "",
    ]
    if card.key_specs:
        lines += ["| Характеристика | Значение | Примечание |", "|---|---|---|"]
        for s in card.key_specs:
            lines.append(f"| {_cell(s.name)} | {_cell(s.value)} | {STATUS_LABELS[s.status]} |")
    else:
        lines.append("Данных нет.")
    lines.append("")

    lines += ["## Поисковые запросы", ""]
    lines += [f"- {q}" for q in card.search_queries] or ["Нет."]
    lines.append("")

    c = card.commercial
    lines += ["## Для менеджера", "", c.summary, "", "**Кому подходит:**", ""]
    lines += [f"- {x}" for x in c.target_customers]
    lines += ["", "**Какие задачи решает:**", ""]
    lines += [f"- {x}" for x in c.tasks]
    lines.append("")

    lines += ["## Отсутствующие данные", ""]
    lines += [f"- {m.field} — {m.reason}" for m in card.missing_fields] or ["Все основные поля заполнены."]
    lines.append("")

    if card.data_conflicts:
        lines += ["## Противоречия во входных данных", ""]
        lines += [f"- {x}" for x in card.data_conflicts]
        lines.append("")

    lines += ["## Проверка", ""]
    lines.append(f"Модель: `{card.model}`, попыток: {card.quality.attempts}, сгенерировано: {card.generated_at}.")
    lines.append("")
    if card.quality.warnings:
        lines += [f"- {w}" for w in card.quality.warnings]
    else:
        lines.append("Все числа и характеристики в тексте найдены во входных данных, длины полей в норме.")
    lines.append("")
    if card.quality.repaired_issues:
        lines += ["Исправлено моделью после повторного запроса:", ""]
        lines += [f"- {i}" for i in card.quality.repaired_issues]
        lines.append("")
    return "\n".join(lines)
