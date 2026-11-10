"""Kiro CLI: ``kiro-cli chat --no-interactive``.

No trusted tools (``--trust-tools=``), so the agent cannot execute anything without
approval, and nobody can approve actions in non-interactive mode.

Output (measured on 2026-11-06, kiro-cli 1.27.3): stdout is text with ANSI colors and
the ``> `` prompt before the response (``\\x1b[38;5;141m> \\x1b[0mok``). Stderr contains
warnings and credits used (``▸ Credits: 0.04 • Time: 1s``). There are no token counts
or native schema support: JSON mode relies only on the prompt instruction.

Modelo inexistente: rc=1 e ``error: Model 'x' does not exist. Available models: ...``
no stderr.
"""

from __future__ import annotations

from .base import CliProvider, Comando, Resultado, resumo, sem_ansi


class KiroProvider(CliProvider):
    nome = "kiro"
    ESPERA_TRANSITORIO_S = 10.0
    ESPERA_COTA_S = 60.0

    def comando(self, prompt: str, modelo: str, json_schema: dict | None) -> Comando:
        return Comando(
            [
                self.cfg.bin,
                "chat",
                "--no-interactive",
                "--trust-tools=",
                "--wrap",
                "never",
                "--model",
                modelo,
                # "--": a prompt beginning with "-" is not treated as an option.
                "--",
                prompt,
            ]
        )

    def interpretar(self, rc: int | None, out: str, err: str) -> Resultado:
        texto = sem_ansi(out).strip()
        if texto.startswith(">"):
            texto = texto[1:].lstrip()
        if rc != 0 or not texto:
            erros = [l for l in sem_ansi(err).splitlines() if l.strip().lower().startswith("error")]
            detalhe = "\n".join(erros) or err or out
            raise self.erro(f"kiro (rc={rc}): {resumo(detalhe)}")
        return Resultado(texto=texto)
