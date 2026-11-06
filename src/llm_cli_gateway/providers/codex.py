"""Codex CLI: ``codex exec --json``, com o prompt pelo stdin (sem limite de argumento).

Sandbox ``read-only`` num diretório vazio, sem sessão gravada e sem as regras de
execpolicy do usuário. O schema vai num arquivo do cwd (``--output-schema``).

Saída (medida em 2026-11-06, codex-cli 0.163.0), JSONL::

    {"type": "thread.started", "thread_id": "..."}
    {"type": "turn.started"}
    {"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "ok"}}
    {"type": "turn.completed", "usage": {"input_tokens": 13290, "cached_input_tokens": 10880,
     "cache_write_input_tokens": 0, "output_tokens": 5, "reasoning_output_tokens": 0}}

Falha: rc=1, eventos ``{"type": "error", "message": "..."}`` e
``{"type": "turn.failed", "error": {"message": "..."}}``; a mensagem pode ser um JSON
da API (``"status": 400``, ``"code": "model_not_found"``). Avisos chegam como
``item.completed`` do tipo ``error`` e não interrompem.
"""

from __future__ import annotations

import json

from .base import CliProvider, Comando, Resultado, resumo

ARQUIVO_SCHEMA = "schema.json"


class CodexProvider(CliProvider):
    nome = "codex"
    PROMPT_NO_ARGV = False
    ESPERA_TRANSITORIO_S = 10.0
    ESPERA_COTA_S = 60.0

    def comando(self, prompt: str, modelo: str, json_schema: dict | None) -> Comando:
        argv = [
            self.cfg.bin,
            "exec",
            "--json",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--skip-git-repo-check",
            "--ignore-rules",
            "--color",
            "never",
            "-m",
            modelo,
        ]
        arquivos = {}
        if json_schema is not None:
            argv += ["--output-schema", ARQUIVO_SCHEMA]
            arquivos[ARQUIVO_SCHEMA] = json.dumps(json_schema, ensure_ascii=False)
        argv.append("-")
        return Comando(argv, stdin=prompt, arquivos=arquivos)

    def interpretar(self, rc: int | None, out: str, err: str) -> Resultado:
        texto = None
        usage: dict = {}
        falha = None
        eventos = 0
        for linha in out.splitlines():
            linha = linha.strip()
            if not linha.startswith("{"):
                continue
            try:
                ev = json.loads(linha)
            except ValueError:
                continue
            eventos += 1
            tipo = ev.get("type")
            if tipo == "item.completed" and (ev.get("item") or {}).get("type") == "agent_message":
                texto = str(ev["item"].get("text") or "")
            elif tipo == "turn.completed":
                usage = ev.get("usage") or {}
            elif tipo == "turn.failed":
                falha = (ev.get("error") or {}).get("message") or "turn.failed"
            elif tipo == "error" and falha is None:
                falha = ev.get("message") or "error"
        if falha is not None or texto is None:
            if falha is None:
                falha = f"sem resposta (rc={rc}, {eventos} eventos): {err or out}"
            raise self.erro(f"codex: {resumo(_mensagem_api(falha))}")
        return Resultado(
            texto=texto,
            # cached_input_tokens já está dentro de input_tokens (convenção da OpenAI).
            entrada=int(usage.get("input_tokens") or 0),
            saida=int(usage.get("output_tokens") or 0),
        )


def _mensagem_api(mensagem: str) -> str:
    """O erro da API vem como JSON dentro da mensagem: mantém status e texto."""
    try:
        dados = json.loads(mensagem)
    except (ValueError, TypeError):
        return mensagem
    if not isinstance(dados, dict):
        return mensagem
    erro = dados.get("error") or {}
    return f"status={dados.get('status')} {erro.get('code') or ''} {erro.get('message') or mensagem}"
