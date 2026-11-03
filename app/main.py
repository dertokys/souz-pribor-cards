import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from .input_parser import InputError
from .llm import LLMError
from .render import to_markdown
from .service import generate_card

INDEX_HTML = Path(__file__).parent / "static" / "index.html"
EXAMPLES_DIR = Path(__file__).parent.parent / "examples" / "input"

app = FastAPI(title="Генератор карточек КИП", version="1.0.0")


@app.exception_handler(InputError)
async def input_error_handler(_: Request, exc: InputError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": exc.message, "details": exc.details})


@app.exception_handler(LLMError)
async def llm_error_handler(_: Request, exc: LLMError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.message, "details": []})


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/examples")
async def examples() -> dict:
    result = {}
    for path in sorted(EXAMPLES_DIR.glob("*.json")):
        try:
            result[path.name.removesuffix(".json")] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
    return result


@app.post("/api/generate")
async def generate(request: Request, format: Literal["json", "markdown"] = "json"):
    body = await request.body()
    card = await run_in_threadpool(generate_card, body)
    if format == "markdown":
        return PlainTextResponse(to_markdown(card), media_type="text/markdown; charset=utf-8")
    return {"card": card.model_dump(), "markdown": to_markdown(card)}
