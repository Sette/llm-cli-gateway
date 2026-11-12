import json
import stat
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_cli_gateway import config as config_mod
from llm_cli_gateway.config import Config
from llm_cli_gateway.main import create_app
from llm_cli_gateway.prompt import extrair_json, montar
from llm_cli_gateway.providers import CLASSES, ProviderConfig

FAKE = Path(__file__).with_name("fake_cli.py")
CLIS = list(CLASSES)


@pytest.fixture(autouse=True)
def sem_esperas(monkeypatch):
    """Use real waits (30 s, 60 s) only in tests that measure them."""
    for classe in CLASSES.values():
        monkeypatch.setattr(classe, "ESPERA_COTA_S", 0.0)
        monkeypatch.setattr(classe, "ESPERA_TRANSITORIO_S", 0.0)


@pytest.fixture
def bins(tmp_path):
    """A fake executable per CLI, running the fake with the test Python interpreter."""
    caminhos = {}
    for cli in CLIS:
        wrapper = tmp_path / f"fake-{cli}"
        wrapper.write_text(f'#!/bin/sh\nFAKE_CLI={cli} exec "{sys.executable}" "{FAKE}" "$@"\n')
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
        caminhos[cli] = str(wrapper)
    return caminhos


@pytest.fixture
def log(tmp_path, monkeypatch):
    caminho = tmp_path / "chamadas.jsonl"
    monkeypatch.setenv("FAKE_CLI_LOG", str(caminho))
    return caminho


def _cfg(bins, api_key=None, timeout_s=30.0, **por_cli):
    """``por_cli``: ``{"agy": {"intervalo_s": 0.3}}`` etc."""
    return Config(
        providers={
            cli: ProviderConfig(
                bin=bins[cli],
                timeout_s=timeout_s,
                modelos=(f"{cli}-m1", f"{cli}-m2"),
                **por_cli.get(cli, {}),
            )
            for cli in CLIS
        },
        api_key=api_key,
        modelo_padrao="modelo-a",
        port=0,
    )


def _client(bins, **kw):
    return TestClient(create_app(_cfg(bins, **kw)))


def _chamadas(log):
    return [json.loads(l) for l in log.read_text().splitlines()]


CORPO = {
    "model": "gemini-x-low",
    "temperature": 0,
    "response_format": {"type": "json_object"},
    "messages": [
        {"role": "system", "content": "You are a writer."},
        {"role": "user", "content": '{"tier": "At Risk"}'},
    ],
    "metadata": {"tags": ["x"]},
}


# --- agy (no prefix: default provider) ---------------------------------------------


def test_chat_ok(bins, log, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "ok")
    r = _client(bins).post("/v1/chat/completions", json=CORPO)
    assert r.status_code == 200, r.text
    d = r.json()
    assert json.loads(d["choices"][0]["message"]["content"]) == {"summary": "ok"}
    assert d["model"] == "gemini-x-low"
    assert d["usage"] == {"prompt_tokens": 120, "completion_tokens": 15, "total_tokens": 135}
    chamada = _chamadas(log)[0]
    assert chamada["cli"] == "agy"
    args = chamada["args"]
    assert args[args.index("--model") + 1] == "gemini-x-low"
    assert "--sandbox" in args and "--disable-slash-commands" in args
    prompt = args[args.index("-p") + 1]
    assert prompt.startswith("You are a writer.")
    assert '{"tier": "At Risk"}' in prompt and "ONLY a valid JSON object" in prompt
    # Runs in an empty temporary directory.
    assert Path(chamada["cwd"]).name.startswith("llm-cli-")
    assert chamada["arquivos"] == {}


def test_prefixo_agy_igual_sem_prefixo(bins, log, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "ok")
    r = _client(bins).post("/v1/chat/completions", json={**CORPO, "model": "agy/gemini-x-low"})
    assert r.status_code == 200 and r.json()["model"] == "agy/gemini-x-low"
    args = _chamadas(log)[0]["args"]
    assert args[args.index("--model") + 1] == "gemini-x-low"


def test_sdk_openai(bins, monkeypatch):
    """Mesmo uso do ClienteLLM do health score."""
    from openai import OpenAI

    monkeypatch.setenv("FAKE_CLI_MODE", "ok")
    tc = _client(bins, api_key="segredo")
    client = OpenAI(base_url="http://testserver/v1", api_key="segredo", http_client=tc)
    for modelo, entrada in (("gemini-x-low", 120), ("claude/haiku", 102), ("codex/gpt-x", 300)):
        resp = client.chat.completions.create(
            model=modelo,
            temperature=0,
            response_format={"type": "json_object"},
            messages=CORPO["messages"],
            extra_body={"metadata": {"tipo": "cliente"}},
        )
        assert json.loads(resp.choices[0].message.content) == {"summary": "ok"}
        assert resp.usage.prompt_tokens == entrada


def test_texto_sem_json_mode(bins, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "texto")
    corpo = {k: v for k, v in CORPO.items() if k != "response_format"}
    r = _client(bins).post("/v1/chat/completions", json=corpo)
    assert r.json()["choices"][0]["message"]["content"] == "hello"


def test_json_invalido_refaz_uma_vez(bins, log, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "invalido_uma_vez")
    monkeypatch.setenv("FAKE_CLI_CONTADOR", str(tmp_path / "n"))
    r = _client(bins).post("/v1/chat/completions", json=CORPO)
    assert r.status_code == 200
    assert json.loads(r.json()["choices"][0]["message"]["content"]) == {"summary": "second"}
    assert r.json()["usage"]["prompt_tokens"] == 240  # soma as duas chamadas
    assert len(_chamadas(log)) == 2


def test_json_invalido_duas_vezes(bins, log, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "invalido")
    r = _client(bins).post("/v1/chat/completions", json=CORPO)
    assert r.status_code == 502
    assert len(_chamadas(log)) == 2


def test_timeout(bins, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "lento")
    monkeypatch.setattr(CLASSES["agy"], "FOLGA_S", 0.0)
    r = _client(bins, timeout_s=1).post("/v1/chat/completions", json=CORPO)
    assert r.status_code == 504


def test_cli_ausente(bins):
    r = _client({**bins, "agy": "/nao/existe/agy"}).post("/v1/chat/completions", json=CORPO)
    assert r.status_code == 503


def test_auth(bins, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "ok")
    c = _client(bins, api_key="segredo")
    assert c.post("/v1/chat/completions", json=CORPO).status_code == 401
    errado = {"Authorization": "Bearer outro"}
    assert c.post("/v1/chat/completions", json=CORPO, headers=errado).status_code == 401
    certo = {"Authorization": "Bearer segredo"}
    assert c.post("/v1/chat/completions", json=CORPO, headers=certo).status_code == 200


def _eventos(r) -> list:
    linhas = [l.removeprefix("data: ") for l in r.text.splitlines() if l.startswith("data: ")]
    assert linhas[-1] == "[DONE]"
    return [json.loads(l) for l in linhas[:-1]]


def test_stream_emulado(bins, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "ok")
    corpo = {**CORPO, "model": "claude/haiku", "stream": True, "stream_options": {"include_usage": True}}
    r = _client(bins).post("/v1/chat/completions", json=corpo)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    eventos = _eventos(r)
    assert all(e["object"] == "chat.completion.chunk" and e["model"] == "claude/haiku" for e in eventos)
    assert eventos[0]["choices"][0]["delta"]["role"] == "assistant"
    assert eventos[0]["choices"][0]["delta"]["content"]
    assert eventos[1]["choices"][0]["finish_reason"] == "stop"
    assert eventos[2]["choices"] == [] and eventos[2]["usage"]["total_tokens"] > 0


def test_stream_sem_usage_por_padrao(bins, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "ok")
    r = _client(bins).post("/v1/chat/completions", json={**CORPO, "stream": True})
    assert r.status_code == 200
    assert all("usage" not in e for e in _eventos(r))


def test_stream_erro_sai_com_status(bins):
    r = _client(bins).post("/v1/chat/completions", json={**CORPO, "model": "xyz/abc", "stream": True})
    assert r.status_code == 400
    assert "error" in r.json()


def test_stream_sdk_openai(bins, monkeypatch):
    from openai import OpenAI

    monkeypatch.setenv("FAKE_CLI_MODE", "ok")
    client = OpenAI(base_url="http://testserver/v1", api_key="x", http_client=_client(bins))
    partes = [
        c.choices[0].delta.content or ""
        for c in client.chat.completions.create(model="codex/gpt-x", messages=CORPO["messages"], stream=True)
        if c.choices
    ]
    assert "".join(partes)


def test_json_schema_vai_para_flag(bins, log, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "ok")
    schema = {"type": "object", "properties": {"resumo": {"type": "string"}}}
    corpo = {**CORPO, "response_format": {"type": "json_schema", "json_schema": {"name": "x", "schema": schema}}}
    assert _client(bins).post("/v1/chat/completions", json=corpo).status_code == 200
    args = _chamadas(log)[0]["args"]
    assert json.loads(args[args.index("--json-schema") + 1]) == schema


def test_modelo_nao_reconhecido_e_transitorio(bins, log, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "modelo_transitorio")
    monkeypatch.setenv("FAKE_CLI_CONTADOR", str(tmp_path / "n"))
    r = _client(bins).post("/v1/chat/completions", json=CORPO)
    assert r.status_code == 200 and len(_chamadas(log)) == 2


def test_intervalo_entre_processos(bins, log, monkeypatch):
    client = _client(bins, agy={"concorrencia": 4, "intervalo_s": 0.3})
    inicio = time.monotonic()
    for _ in range(3):
        assert client.post("/v1/chat/completions", json=CORPO).status_code == 200
    assert time.monotonic() - inicio >= 0.6


def test_cota_pausa_e_devolve_retry_after(bins, log, monkeypatch):
    monkeypatch.setattr(CLASSES["agy"], "ESPERA_COTA_S", 0.2)
    monkeypatch.setenv("FAKE_CLI_MODE", "cota")
    inicio = time.monotonic()
    r = _client(bins).post("/v1/chat/completions", json=CORPO)
    assert r.status_code == 429 and r.headers["retry-after"] == "0"
    # retries=2 (ProviderConfig default): 3 processes, with two 0.2-second waits
    assert len(_chamadas(log)) == 3 and time.monotonic() - inicio >= 0.4


def test_modelo_com_lixo_e_recusado_na_hora(bins, log):
    corpo = {**CORPO, "model": "gemini-x-low# .env comment"}
    r = _client(bins).post("/v1/chat/completions", json=corpo)
    assert r.status_code == 400 and not log.exists()


# --- roteamento e os outros CLIs ----------------------------------------------------


def test_prefixo_desconhecido(bins, log):
    r = _client(bins).post("/v1/chat/completions", json={**CORPO, "model": "gemini/x"})
    assert r.status_code == 400 and "claude/<model>" in r.json()["error"]["message"]
    assert not log.exists()


def test_provedor_desligado(bins, log):
    r = _client(bins, claude={"ativo": False}).post(
        "/v1/chat/completions", json={**CORPO, "model": "claude/haiku"}
    )
    assert r.status_code == 503 and not log.exists()


def test_claude(bins, log, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "ok")
    r = _client(bins).post("/v1/chat/completions", json={**CORPO, "model": "claude/haiku"})
    assert r.status_code == 200, r.text
    assert r.json()["usage"] == {"prompt_tokens": 102, "completion_tokens": 7, "total_tokens": 109}
    chamada = _chamadas(log)[0]
    assert chamada["cli"] == "claude"
    args = chamada["args"]
    assert args[args.index("--model") + 1] == "haiku"
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--setting-sources") + 1] == ""
    assert "-p" in args and "--no-session-persistence" in args and "--strict-mcp-config" in args
    # The prompt is passed through stdin, not argv.
    assert "ONLY a valid JSON object" in chamada["stdin"]
    assert not any("Em Risco" in a for a in args)


def test_claude_structured_output(bins):
    from llm_cli_gateway.providers.claude import ClaudeProvider

    p = ClaudeProvider(ProviderConfig(bin=bins["claude"]))
    out = json.dumps({"type": "result", "subtype": "success", "is_error": False,
                      "result": "texto livre", "structured_output": {"a": 1}, "usage": {}})
    assert p.interpretar(0, out, "").texto == '{"a": 1}'


def test_codex(bins, log, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "ok")
    schema = {"type": "object", "properties": {"resumo": {"type": "string"}}}
    corpo = {**CORPO, "model": "codex/gpt-x",
             "response_format": {"type": "json_schema", "json_schema": {"name": "x", "schema": schema}}}
    r = _client(bins).post("/v1/chat/completions", json=corpo)
    assert r.status_code == 200, r.text
    assert json.loads(r.json()["choices"][0]["message"]["content"]) == {"summary": "ok"}
    # cached_input_tokens is already included in input_tokens.
    assert r.json()["usage"] == {"prompt_tokens": 300, "completion_tokens": 9, "total_tokens": 309}
    chamada = _chamadas(log)[0]
    args = chamada["args"]
    assert args[:2] == ["exec", "--json"] and args[-1] == "-"
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert args[args.index("-m") + 1] == "gpt-x"
    assert "--ephemeral" in args and "--skip-git-repo-check" in args and "--ignore-rules" in args
    assert "ONLY a valid JSON object" in chamada["stdin"]
    # The schema is written to a temporary cwd file that is removed afterward.
    nome = args[args.index("--output-schema") + 1]
    assert json.loads(chamada["arquivos"][nome]) == schema
    assert not Path(chamada["cwd"]).exists()


def test_kiro(bins, log, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "ok")
    r = _client(bins).post("/v1/chat/completions", json={**CORPO, "model": "kiro/claude-haiku-4.5"})
    assert r.status_code == 200, r.text
    assert json.loads(r.json()["choices"][0]["message"]["content"]) == {"summary": "ok"}
    assert r.json()["usage"]["total_tokens"] == 0
    args = _chamadas(log)[0]["args"]
    assert args[:2] == ["chat", "--no-interactive"] and "--trust-tools=" in args
    assert args[args.index("--model") + 1] == "claude-haiku-4.5"
    assert args[-2] == "--" and "ONLY a valid JSON object" in args[-1]


def test_kiro_texto_sem_ansi(bins, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "texto")
    corpo = {k: v for k, v in CORPO.items() if k != "response_format"}
    r = _client(bins).post("/v1/chat/completions", json={**corpo, "model": "kiro/auto"})
    assert r.json()["choices"][0]["message"]["content"] == "hello"


@pytest.mark.parametrize("cli", CLIS)
@pytest.mark.parametrize("modo,status", [("falha", 502), ("cota", 429), ("lixo", 502)])
def test_erros(bins, monkeypatch, cli, modo, status):
    monkeypatch.setenv("FAKE_CLI_MODE", modo)
    r = _client(bins).post("/v1/chat/completions", json={**CORPO, "model": f"{cli}/m"})
    assert r.status_code == status, r.text
    assert "error" in r.json()


@pytest.mark.parametrize(
    "cli,mensagem",
    [
        ("claude", "There's an issue with the selected model (x). It may not exist"),
        ("codex", "The 'x' model is not supported. model_not_found"),
        ("kiro", "Model 'x' does not exist. Available models: auto, glm-5"),
    ],
)
def test_modelo_inexistente_404(bins, cli, mensagem):
    err = CLASSES[cli](ProviderConfig(bin=bins[cli])).erro(mensagem)
    assert err.status_http == 404 and not err.transitorio


def test_erro_do_kiro_traz_a_mensagem(bins, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "falha")
    r = _client(bins).post("/v1/chat/completions", json={**CORPO, "model": "kiro/m"})
    mensagem = r.json()["error"]["message"]
    assert "error: something went wrong" in mensagem and "WARNING" not in mensagem and "\x1b" not in mensagem


def test_models_e_health(bins):
    c = _client(bins, kiro={"ativo": False})
    ids = [m["id"] for m in c.get("/v1/models").json()["data"]]
    assert ids == ["agy/model-a", "agy/model-b", "claude/claude-m1", "claude/claude-m2",
                   "codex/codex-m1", "codex/codex-m2"]
    h = c.get("/health")
    assert h.status_code == 200
    assert h.json()["providers"] == {"agy": True, "claude": True, "codex": True, "kiro": False}


def test_health_sem_nenhum_cli(bins):
    c = _client({cli: f"/nao/existe/{cli}" for cli in CLIS})
    assert c.get("/health").status_code == 503


# --- configuration -----------------------------------------------------------------


def test_config_nomes_antigos_do_agy(monkeypatch):
    for var in ("API_KEY", "MODELO_PADRAO"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AGY_API_KEY", "velha")
    monkeypatch.setenv("AGY_MODELO_PADRAO", "gemini-velho")
    cfg = config_mod.load()
    assert cfg.api_key == "velha" and cfg.modelo_padrao == "gemini-velho"
    monkeypatch.setenv("API_KEY", "nova")
    assert config_mod.load().api_key == "nova"


def test_config_por_cli(monkeypatch):
    monkeypatch.setenv("CLAUDE_BIN", "/opt/claude")
    monkeypatch.setenv("CLAUDE_ATIVO", "0")
    monkeypatch.setenv("CODEX_MODELOS", "a, b")
    monkeypatch.setenv("KIRO_CONCORRENCIA", "5")
    p = config_mod.load().providers
    assert p["claude"].bin == "/opt/claude" and not p["claude"].ativo
    assert p["codex"].modelos == ("a", "b")
    assert p["kiro"].concorrencia == 5 and p["kiro"].bin == "kiro-cli"
    assert p["agy"].intervalo_s == 5.0 and p["agy"].tentativas == 3


# --- prompt -------------------------------------------------------------------------


def test_nova_tentativa_vira_transcricao():
    """Additional pipeline messages (refusal and correction)."""
    p = montar(
        [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "input"},
            {"role": "assistant", "content": '{"summary": "has 12"}'},
            {"role": "user", "content": "Remove the numbers."},
        ],
        json_mode=True,
    )
    assert p.startswith("SYS")
    assert p.index("### User\ninput") < p.index("### Assistant\n{") < p.index("### User\nRemove")
    assert "Respond to the last User message." in p


def test_conteudo_em_partes():
    p = montar([{"role": "user", "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}], False)
    assert p == "a\nb"


def test_cerca_markdown(bins, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_MODE", "cerca")
    r = _client(bins).post("/v1/chat/completions", json=CORPO)
    assert json.loads(r.json()["choices"][0]["message"]["content"]) == {"summary": "fenced"}


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
