import argparse
import json
import sys
from pathlib import Path

from .input_parser import InputError
from .llm import LLMConfigError, LLMError, LLMRateLimited
from .render import to_markdown
from .service import generate_card


def main() -> int:
    parser = argparse.ArgumentParser(description="Сгенерировать черновик карточки товара из JSON")
    parser.add_argument("inputs", nargs="+", type=Path, help="JSON-файлы с данными товаров")
    parser.add_argument("-o", "--out", type=Path, help="папка для результатов (<имя>.json и <имя>.md)")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    exit_code = 0
    for path in args.inputs:
        try:
            card = generate_card(path.read_bytes())
        except FileNotFoundError:
            print(f"[{path}] файл не найден", file=sys.stderr)
            exit_code = 2
            continue
        except InputError as e:
            details = "".join(f"\n  - {d}" for d in e.details)
            print(f"[{path}] {e.message}{details}", file=sys.stderr)
            exit_code = 2
            continue
        except (LLMConfigError, LLMRateLimited) as e:
            print(f"[{path}] Ошибка LLM: {e.message} — обработка остановлена", file=sys.stderr)
            return 3
        except LLMError as e:
            print(f"[{path}] Ошибка LLM: {e.message}", file=sys.stderr)
            exit_code = 3
            continue

        markdown = to_markdown(card)
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            stem = path.name.removesuffix(".json")
            (args.out / f"{stem}.json").write_text(
                json.dumps(card.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            (args.out / f"{stem}.md").write_text(markdown, encoding="utf-8")
            status = "требует проверки" if card.quality.needs_review else "ок"
            print(f"[{path}] готово ({status}, попыток: {card.quality.attempts}) → {args.out / stem}.md", file=sys.stderr)
        else:
            print(markdown)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
