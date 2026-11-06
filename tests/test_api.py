import json
import os
import stat
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agy_openai_api.config import Config
from agy_openai_api.main import create_app
from agy_openai_api.prompt import extrair_json, montar

FAKE = Path(__file__).with_name("fake_agy.py")


@pytest.fixture
def fake_bin(tmp_path):
    # Wrapper executável que roda o fake com o mesmo Python dos testes.
    wrapper = tmp_path / "agy"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    return str(wrapper)


@pytest.fixture
def log(tmp_path, monkeypatch):
    caminho = tmp_path / "chamadas.jsonl"
    monkeypatch.setenv("FAKE_AGY_LOG", str(caminho))
    return caminho


def _client(fake_bin, api_key=None, timeout_s=30.0):
    cfg = Config(
        agy_bin=fake_bin,
        api_key=api_key,
        concorrencia=2,
        timeout_s=timeout_s,
        modelo_padrao="modelo-a",
        host="127.0.0.1",
        port=0,
    )
    return TestClient(create_app(cfg))


def _chamadas(log):
    return [json.loads(l) for l in log.read_text().splitlines()]


CORPO = {
    "model": "gemini-x-low",
    "temperature": 0,
    "response_format": {"type": "json_object"},
    "messages": [
        {"role": "system", "content": "Você é um redator."},
        {"role": "user", "content": '{"faixa": "Em Risco"}'},
    ],
    "metadata": {"tags": ["x"]},
}


def test_chat_ok(fake_bin, log, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_MODE", "ok")
    r = _client(fake_bin).post("/v1/chat/completions", json=CORPO)
    assert r.status_code == 200, r.text
    d = r.json()
    assert json.loads(d["choices"][0]["message"]["content"]) == {"resumo": "ok"}
    assert d["model"] == "gemini-x-low"
    assert d["usage"] == {"prompt_tokens": 120, "completion_tokens": 15, "total_tokens": 135}
    args = _chamadas(log)[0]["args"]
    assert args[args.index("--model") + 1] == "gemini-x-low"
    assert "--sandbox" in args and "--disable-slash-commands" in args
    prompt = args[args.index("-p") + 1]
    assert prompt.startswith("Você é um redator.")
    assert '{"faixa": "Em Risco"}' in prompt and "SOMENTE com um objeto JSON" in prompt
    # Roda num diretório temporário vazio.
    assert Path(_chamadas(log)[0]["cwd"]).name.startswith("agy-api-")


def test_sdk_openai(fake_bin, monkeypatch):
    """Mesmo uso do ClienteLLM do health score."""
    from openai import OpenAI

    monkeypatch.setenv("FAKE_AGY_MODE", "ok")
    tc = _client(fake_bin, api_key="segredo")
    client = OpenAI(base_url="http://testserver/v1", api_key="segredo", http_client=tc)
    resp = client.chat.completions.create(
        model="gemini-x-low",
        temperature=0,
        response_format={"type": "json_object"},
        messages=CORPO["messages"],
        extra_body={"metadata": {"tipo": "cliente"}},
    )
    assert json.loads(resp.choices[0].message.content) == {"resumo": "ok"}
    assert resp.usage.prompt_tokens == 120


def test_texto_sem_json_mode(fake_bin, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_MODE", "texto")
    corpo = {k: v for k, v in CORPO.items() if k != "response_format"}
    r = _client(fake_bin).post("/v1/chat/completions", json=corpo)
    assert r.json()["choices"][0]["message"]["content"] == "olá"


def test_cerca_markdown(fake_bin, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_MODE", "cerca")
    r = _client(fake_bin).post("/v1/chat/completions", json=CORPO)
    assert json.loads(r.json()["choices"][0]["message"]["content"]) == {"resumo": "cercado"}


def test_json_invalido_refaz_uma_vez(fake_bin, log, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_MODE", "invalido_uma_vez")
    monkeypatch.setenv("FAKE_AGY_CONTADOR", str(tmp_path / "n"))
    r = _client(fake_bin).post("/v1/chat/completions", json=CORPO)
    assert r.status_code == 200
    assert json.loads(r.json()["choices"][0]["message"]["content"]) == {"resumo": "segunda"}
    assert r.json()["usage"]["prompt_tokens"] == 240  # soma as duas chamadas
    assert len(_chamadas(log)) == 2


def test_json_invalido_duas_vezes(fake_bin, log, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_MODE", "invalido")
    r = _client(fake_bin).post("/v1/chat/completions", json=CORPO)
    assert r.status_code == 502
    assert len(_chamadas(log)) == 2


def test_timeout(fake_bin, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_MODE", "lento")
    from agy_openai_api.agy import Agy

    monkeypatch.setattr(Agy, "FOLGA_S", 0.0)
    r = _client(fake_bin, timeout_s=1).post("/v1/chat/completions", json=CORPO)
    assert r.status_code == 504


@pytest.mark.parametrize("modo,status", [("falha", 502), ("cota", 429), ("lixo", 502)])
def test_erros(fake_bin, monkeypatch, modo, status):
    from agy_openai_api.agy import Agy

    monkeypatch.setattr(Agy, "ESPERA_COTA_S", 0.0)
    monkeypatch.setattr(Agy, "ESPERA_TRANSITORIO_S", 0.0)
    monkeypatch.setenv("FAKE_AGY_MODE", modo)
    r = _client(fake_bin).post("/v1/chat/completions", json=CORPO)
    assert r.status_code == status
    assert "error" in r.json()


def test_agy_ausente():
    r = _client("/nao/existe/agy").post("/v1/chat/completions", json=CORPO)
    assert r.status_code == 503


def test_auth(fake_bin, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_MODE", "ok")
    c = _client(fake_bin, api_key="segredo")
    assert c.post("/v1/chat/completions", json=CORPO).status_code == 401
    errado = {"Authorization": "Bearer outro"}
    assert c.post("/v1/chat/completions", json=CORPO, headers=errado).status_code == 401
    certo = {"Authorization": "Bearer segredo"}
    assert c.post("/v1/chat/completions", json=CORPO, headers=certo).status_code == 200


def test_stream_recusado(fake_bin):
    r = _client(fake_bin).post("/v1/chat/completions", json={**CORPO, "stream": True})
    assert r.status_code == 400


def test_models_e_health(fake_bin):
    c = _client(fake_bin)
    ids = [m["id"] for m in c.get("/v1/models").json()["data"]]
    assert ids == ["modelo-a", "modelo-b"]
    assert c.get("/health").status_code == 200


def test_json_schema_vai_para_flag(fake_bin, log, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_MODE", "ok")
    schema = {"type": "object", "properties": {"resumo": {"type": "string"}}}
    corpo = {**CORPO, "response_format": {"type": "json_schema", "json_schema": {"name": "x", "schema": schema}}}
    assert _client(fake_bin).post("/v1/chat/completions", json=corpo).status_code == 200
    args = _chamadas(log)[0]["args"]
    assert json.loads(args[args.index("--json-schema") + 1]) == schema


def test_nova_tentativa_vira_transcricao():
    """Mensagens extras do pipeline (resposta recusada + correção)."""
    p = montar(
        [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "entrada"},
            {"role": "assistant", "content": '{"resumo": "tem 12"}'},
            {"role": "user", "content": "Tire os números."},
        ],
        json_mode=True,
    )
    assert p.startswith("SYS")
    assert p.index("### Usuário\nentrada") < p.index("### Assistente\n{") < p.index("### Usuário\nTire")
    assert "Responda à última mensagem do Usuário." in p


def test_conteudo_em_partes():
    p = montar([{"role": "user", "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}], False)
    assert p == "a\nb"


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ('{"a": 1}', '{"a": 1}'),
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ('Claro! {"a": {"b": 2}} fim', '{"a": {"b": 2}}'),
        ("sem json", None),
        ("[1, 2]", None),
    ],
)
def test_extrair_json(texto, esperado):
    assert extrair_json(texto) == esperado


def test_modelo_nao_reconhecido_e_transitorio(fake_bin, log, tmp_path, monkeypatch):
    from agy_openai_api.agy import Agy

    monkeypatch.setattr(Agy, "ESPERA_TRANSITORIO_S", 0.0)
    monkeypatch.setenv("FAKE_AGY_MODE", "modelo_transitorio")
    monkeypatch.setenv("FAKE_AGY_CONTADOR", str(tmp_path / "n"))
    r = _client(fake_bin).post("/v1/chat/completions", json=CORPO)
    assert r.status_code == 200 and len(_chamadas(log)) == 2


def test_intervalo_entre_processos(fake_bin, log, monkeypatch):
    import time

    cfg = Config(
        agy_bin=fake_bin, api_key=None, concorrencia=4, timeout_s=30.0,
        modelo_padrao="modelo-a", host="127.0.0.1", port=0, intervalo_s=0.3,
    )
    client = TestClient(create_app(cfg))
    inicio = time.monotonic()
    for _ in range(3):
        assert client.post("/v1/chat/completions", json=CORPO).status_code == 200
    assert time.monotonic() - inicio >= 0.6


def test_cota_pausa_e_devolve_retry_after(fake_bin, log, monkeypatch):
    from agy_openai_api.agy import Agy

    monkeypatch.setattr(Agy, "ESPERA_COTA_S", 0.2)
    monkeypatch.setattr(Agy, "ESPERA_TRANSITORIO_S", 0.0)
    monkeypatch.setenv("FAKE_AGY_MODE", "cota")
    import time

    inicio = time.monotonic()
    r = _client(fake_bin).post("/v1/chat/completions", json=CORPO)
    assert r.status_code == 429 and r.headers["retry-after"] == "0"
    # tentativas=2 (padrão do Config): 3 processos, com duas pausas de 0,2 s
    assert len(_chamadas(log)) == 3 and time.monotonic() - inicio >= 0.4


def test_modelo_com_lixo_e_recusado_na_hora(fake_bin, log):
    corpo = {**CORPO, "model": "gemini-x-low# comentário do .env"}
    r = _client(fake_bin).post("/v1/chat/completions", json=corpo)
    assert r.status_code == 400 and not log.exists()
