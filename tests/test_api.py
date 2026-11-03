import json

import pytest
from fastapi.testclient import TestClient

from app import service
from app.config import get_settings
from app.generator import CardGenerator
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
