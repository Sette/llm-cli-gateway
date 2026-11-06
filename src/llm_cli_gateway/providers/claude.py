"""Claude Code: ``claude -p`` com ``--output-format json`` e o prompt pelo stdin.

Sem ferramentas (``--tools ""``), sem MCP, sem settings do usuário (hooks, plugins) e
sem sessão gravada. Não usa ``--bare``, que exige ``ANTHROPIC_API_KEY`` e ignora o
login OAuth da assinatura.

Saída (medida em 2026-11-06, Claude Code 2.1.319), uma linha JSON::

    {"type": "result", "subtype": "success", "is_error": false, "result": "ok",
     "structured_output": {...},            # só com --json-schema
     "api_error_status": null, "num_turns": 1, "duration_ms": 1148,
     "usage": {"input_tokens": 2, "cache_creation_input_tokens": 2849,
               "cache_read_input_tokens": 649, "output_tokens": 4, ...}, ...}

Modelo inexistente: rc=1, ``is_error: true``, ``api_error_status: 404`` e a mensagem
em ``result``.
"""

from __future__ import annotations

import json

from .base import CliProvider, Comando, ErroCli, Resultado, resumo


class ClaudeProvider(CliProvider):
    nome = "claude"
    PROMPT_NO_ARGV = False
    ESPERA_TRANSITORIO_S = 10.0
    ESPERA_COTA_S = 60.0

    def comando(self, prompt: str, modelo: str, json_schema: dict | None) -> Comando:
        argv = [
            self.cfg.bin,
            "-p",
            "--model",
            modelo,
            "--output-format",
            "json",
            "--tools",
            "",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--setting-sources",
            "",
        ]
        if json_schema is not None:
            argv += ["--json-schema", json.dumps(json_schema, ensure_ascii=False)]
        # Pelo stdin: o -p do claude é flag e o prompt seria posicional (um prompt que
        # começa com "-" viraria opção); também não tem o limite de argumento do Linux.
        return Comando(argv, stdin=prompt)

    def interpretar(self, rc: int | None, out: str, err: str) -> Resultado:
        dados = None
        for linha in reversed(out.strip().splitlines()):
            linha = linha.strip()
            if linha.startswith("{"):
                try:
                    dados = json.loads(linha)
                    break
                except ValueError:
                    continue
        if not isinstance(dados, dict):
            raise self.erro(f"Saída do claude não é JSON (rc={rc}): {resumo(err or out)}")
        if dados.get("is_error") or dados.get("subtype") not in (None, "success"):
            status = dados.get("api_error_status")
            mensagem = f"claude: {resumo(str(dados.get('result') or err or dados.get('subtype')))}"
            if status == 429:
                raise ErroCli(429, mensagem, transitorio=True)
            if status == 529 or (isinstance(status, int) and status >= 500):
                raise ErroCli(503, mensagem, transitorio=True)
            raise self.erro(mensagem)
        if dados.get("structured_output") is not None:
            texto = json.dumps(dados["structured_output"], ensure_ascii=False)
        else:
            texto = str(dados.get("result") or "")
        usage = dados.get("usage") or {}
        return Resultado(
            texto=texto,
            entrada=sum(
                int(usage.get(k) or 0)
                for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
            ),
            saida=int(usage.get("output_tokens") or 0),
            duracao_s=float(dados.get("duration_ms") or 0) / 1000,
        )
