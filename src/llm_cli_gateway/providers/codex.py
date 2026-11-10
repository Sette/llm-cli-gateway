"""Codex CLI: ``codex exec --json``, with the prompt on stdin (no argument size limit).

``read-only`` sandbox in an empty directory, without a saved session or the user's
execpolicy rules. The schema is written to a file in cwd (``--output-schema``).

Output (measured on 2026-11-06, codex-cli 0.163.0), JSONL::

    {"type": "thread.started", "thread_id": "..."}
    {"type": "turn.started"}
    {"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "ok"}}
    {"type": "turn.completed", "usage": {"input_tokens": 13290, "cached_input_tokens": 10880,
     "cache_write_input_tokens": 0, "output_tokens": 5, "reasoning_output_tokens": 0}}

Failure: rc=1, events ``{"type": "error", "message": "..."}`` and
``{"type": "turn.failed", "error": {"message": "..."}}``; the message may be API JSON
an API error (``"status": 400``, ``"code": "model_not_found"``). Warnings arrive as
``item.completed`` events of type ``error`` and do not interrupt execution.
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
                falha = f"no response (rc={rc}, {eventos} events): {err or out}"
            raise self.erro(f"codex: {resumo(_mensagem_api(falha))}")
        return Resultado(
            texto=texto,
            # cached_input_tokens is already included in input_tokens (OpenAI convention).
            entrada=int(usage.get("input_tokens") or 0),
            saida=int(usage.get("output_tokens") or 0),
        )


def _mensagem_api(mensagem: str) -> str:
    """The API error is JSON inside the message; preserve its status and text."""
    try:
        dados = json.loads(mensagem)
    except (ValueError, TypeError):
        return mensagem
    if not isinstance(dados, dict):
        return mensagem
    erro = dados.get("error") or {}
    return f"status={dados.get('status')} {erro.get('code') or ''} {erro.get('message') or mensagem}"
