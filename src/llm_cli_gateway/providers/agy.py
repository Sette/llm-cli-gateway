"""Antigravity CLI: ``agy -p`` (print mode) with ``--output-format json``.

Successful output (measured on 2026-11-06, agy 1.5.2)::

    {"conversation_id": "...", "status": "SUCCESS", "response": "...",
     "duration_seconds": 3.9, "num_turns": 1,
     "usage": {"input_tokens": 6402, "output_tokens": 22, "thinking_tokens": 0,
               "cache_read_tokens": 0, "total_tokens": 6424}}
"""

from __future__ import annotations

import asyncio
import json
import re

from .base import CliProvider, Comando, ErroCli, Resultado, resumo


class AgyProvider(CliProvider):
    nome = "agy"
    # Google's quota is per minute, and without quota agy cannot load the model list:
    # waiting less than a minute only consumes more quota. Each agy process consumes
    # the "Management Requests per minute per user" quota when it starts.
    ESPERA_TRANSITORIO_S = 30.0
    ESPERA_COTA_S = 60.0
    # When several agy processes start together, some fail to load the model list and
    # reject a valid model (measured on 2026-11-06, 8 in parallel). A retry succeeds.
    TRANSITORIO = re.compile(r"not recognized as a known model|invalid model selection", re.I)

    def comando(self, prompt: str, modelo: str, json_schema: dict | None) -> Comando:
        argv = [
            self.cfg.bin,
            "-p",
            prompt,
            "--model",
            modelo,
            "--sandbox",
            "--disable-slash-commands",
            "--output-format",
            "json",
            "--print-timeout",
            f"{int(self.cfg.timeout_s)}s",
        ]
        if json_schema is not None:
            argv += ["--json-schema", json.dumps(json_schema, ensure_ascii=False)]
        return Comando(argv)

    def interpretar(self, rc: int | None, out: str, err: str) -> Resultado:
        # Output may contain warnings before the JSON (e.g. "warning: ...").
        dados = None
        for linha in reversed(out.strip().splitlines()):
            linha = linha.strip()
            if linha.startswith("{"):
                try:
                    dados = json.loads(linha)
                    break
                except ValueError:
                    continue
        if dados is None:
            try:
                dados = json.loads(out[out.find("{") :]) if "{" in out else None
            except ValueError:
                dados = None
        if not isinstance(dados, dict):
            raise self.erro(f"agy output is not JSON (rc={rc}): {resumo(err or out)}")
        status = str(dados.get("status", ""))
        if status.upper() == "TIMEOUT":
            raise ErroCli(504, "agy: print-timeout atingido.")
        if status.upper() != "SUCCESS":
            detalhe = dados.get("error") or dados.get("message") or dados.get("response") or err
            raise self.erro(f"agy status={status}: {resumo(str(detalhe))}")
        usage = dados.get("usage") or {}
        return Resultado(
            texto=str(dados.get("response") or ""),
            entrada=int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_tokens") or 0),
            saida=int(usage.get("output_tokens") or 0) + int(usage.get("thinking_tokens") or 0),
            duracao_s=float(dados.get("duration_seconds") or 0),
        )

    async def modelos(self) -> list[str]:
        proc = await asyncio.create_subprocess_exec(
            self.cfg.bin,
            "models",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        ids = []
        for linha in out.decode(errors="replace").splitlines():
            partes = linha.split("\t")
            if len(partes) >= 2 and partes[0].strip():
                ids.append(partes[0].strip())
        return ids or list(self.cfg.modelos)
