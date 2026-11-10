"""Claude Code: ``claude -p`` with ``--output-format json`` and the prompt on stdin.

No tools (``--tools ""``), MCP, user settings (hooks, plugins), or saved session.
Does not use ``--bare``, which requires ``ANTHROPIC_API_KEY`` and ignores subscription
OAuth login.

Output (measured on 2026-11-06, Claude Code 2.1.319), one JSON line::

    {"type": "result", "subtype": "success", "is_error": false, "result": "ok",
     "structured_output": {...},            # only with --json-schema
     "api_error_status": null, "num_turns": 1, "duration_ms": 1148,
     "usage": {"input_tokens": 2, "cache_creation_input_tokens": 2849,
               "cache_read_input_tokens": 649, "output_tokens": 4, ...}, ...}

Unknown model: rc=1, ``is_error: true``, ``api_error_status: 404``, with the message
in ``result``.
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
        # Use stdin: claude's -p is a flag and a positional prompt beginning with "-"
        # would be treated as an option. This also avoids Linux's argument length limit.
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
            raise self.erro(f"claude output is not JSON (rc={rc}): {resumo(err or out)}")
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
