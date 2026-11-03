import json
import sys

import pytest
from fastapi.testclient import TestClient

from app import service
from app.config import get_settings
from app.generator import CardGenerator
from app.input_parser import parse_product
from app.llm import LLMConfigError, LLMUnavailable, OpenAICompatibleClient
from app.main import app

from .conftest import DESCRIPTION, SPECS, FakeLLM, make_card

PRODUCT = {"name": "ПД100-ДИ1,0-115-0,5", "manufacturer": "ОВЕН", "specs": SPECS, "description": DESCRIPTION}


@pytest.fixture
def client(monkeypatch):
    def use(responses):
        monkeypatch.setattr(service, "get_generator", lambda: CardGenerator(FakeLLM(responses)))

    test_client = TestClient(app)
    test_client.use = use
    return test_client


def test_index_and_examples(client):
    assert client.get("/").status_code == 200
    examples = client.get("/api/examples").json()
    assert "oven-pd100-di1-0-115-0-5" in examples


def test_generate_json(client):
    client.use([make_card()])
    r = client.post("/api/generate", content=json.dumps(PRODUCT, ensure_ascii=False).encode())
    assert r.status_code == 200
    body = r.json()
    assert body["card"]["seo_title"]
    assert body["markdown"].startswith("# Черновик карточки")


def test_generate_markdown(client):
    client.use([make_card()])
    r = client.post("/api/generate?format=markdown", content=json.dumps(PRODUCT, ensure_ascii=False).encode())
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")


@pytest.mark.parametrize("body, fragment", [
    (b"", "Пустой запрос"),
    (b'{"name": "x",}', "Некорректный JSON"),
    ('{"name": "ОВЕН"}'.encode("cp1251"), "UTF-8"),
    (b"[1]", "JSON-объект"),
    (b'{"manufacturer": "X"}', "не прошли проверку"),
])
def test_input_errors_are_422(client, body, fragment):
    r = client.post("/api/generate", content=body)
    assert r.status_code == 422
    assert fragment in r.json()["error"]


def test_llm_error_status_is_mapped(client):
    client.use([LLMUnavailable("нет сети")])
    r = client.post("/api/generate", content=json.dumps(PRODUCT, ensure_ascii=False).encode())
    assert r.status_code == 503
    assert r.json()["error"] == "нет сети"


def test_client_without_key_raises_config_error(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    with pytest.raises(LLMConfigError):
        OpenAICompatibleClient(get_settings())


def test_invalid_number_in_env_gives_config_error(monkeypatch):
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "abc")
    service.get_generator.cache_clear()
    try:
        r = TestClient(app).post("/api/generate", content=json.dumps(PRODUCT, ensure_ascii=False).encode())
    finally:
        service.get_generator.cache_clear()
    assert r.status_code == 500
    assert "LLM_MAX_ATTEMPTS" in r.json()["error"]


def test_cli_continues_after_product_error(monkeypatch, tmp_path, capsys):
    from app import cli
    from app.llm import LLMBadResponse

    files = []
    for i in range(2):
        f = tmp_path / f"p{i}.json"
        f.write_text(json.dumps(PRODUCT, ensure_ascii=False), encoding="utf-8")
        files.append(str(f))
    calls = []

    def fake(raw):
        calls.append(raw)
        if len(calls) == 1:
            raise LLMBadResponse("плохой JSON")
        return CardGenerator(FakeLLM([make_card()])).generate(*parse_product(raw))

    monkeypatch.setattr(cli, "generate_card", fake)
    monkeypatch.setattr(sys, "argv", ["cli", *files, "-o", str(tmp_path / "out")])
    assert cli.main() == 3
    assert len(calls) == 2
    assert (tmp_path / "out" / "p1.md").exists()


def test_config_error_clears_cached_generator(monkeypatch):
    calls = []

    class Broken:
        def generate(self, product, missing):
            calls.append(1)
            raise LLMConfigError("ключ отклонён")

    service.get_generator.cache_clear()
    monkeypatch.setattr(service, "OpenAICompatibleClient", lambda settings: None)
    service.get_generator()
    assert service.get_generator.cache_info().currsize == 1
    with pytest.raises(LLMConfigError):
        service.generate_card(json.dumps(PRODUCT, ensure_ascii=False), generator=Broken())
    assert service.get_generator.cache_info().currsize == 0
