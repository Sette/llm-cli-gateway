"""Behavior shared by all CLIs: subprocesses, pacing, retries, timeouts, and errors.

Each CLI is a :class:`CliProvider` subclass that defines how to build the command
(:meth:`comando`) and parse its output (:meth:`interpretar`).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("llm_cli_gateway")

# A Linux argument can be at most 128 KiB (MAX_ARG_STRLEN).
MAX_PROMPT_BYTES = 120_000
_COTA = re.compile(
    r"quota|rate.?limit|resource.?exhausted|too many requests|usage limit|\b429\b", re.I
)
# Unknown model (claude, codex, kiro): 404, as with OpenAI. agy sometimes rejects
# a valid model by mistake; that case is handled separately as transient.
_MODELO_INEXISTENTE = re.compile(
    r"model_not_found|issue with the selected model|model '[^']*' does not exist", re.I
)
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-_]")


class ErroCli(Exception):
    def __init__(self, status_http: int, mensagem: str, transitorio: bool = False):
        super().__init__(mensagem)
        self.status_http = status_http
        self.mensagem = mensagem
        self.transitorio = transitorio


@dataclass
class Resultado:
    texto: str
    # Normalized: input = prompt (including cache), output = response (including reasoning).
    entrada: int = 0
    saida: int = 0
    duracao_s: float = 0.0


@dataclass
class Comando:
    argv: list[str]
    stdin: str | None = None
    # Files read by the command (e.g. the Codex schema), created in the temporary cwd.
    arquivos: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderConfig:
    bin: str
    ativo: bool = True
    concorrencia: int = 2
    timeout_s: float = 180.0
    intervalo_s: float = 0.0
    tentativas: int = 2
    # Fixed list for /v1/models (agy lists models through its own CLI).
    modelos: tuple[str, ...] = ()


def resumo(texto: str, limite: int = 500) -> str:
    texto = " ".join(sem_ansi(texto).split())
    return texto if len(texto) <= limite else texto[:limite] + "…"


def sem_ansi(texto: str) -> str:
    return _ANSI.sub("", texto)


class CliProvider:
    nome = ""
    # Grace period beyond the CLI's own timeout before killing the process.
    FOLGA_S = 15.0
    # Wait before retrying a transient error (doubles on each attempt).
    ESPERA_TRANSITORIO_S = 30.0
    # Quota pause applies to all processes for this CLI, not just the failed request.
    ESPERA_COTA_S = 60.0
    # When the prompt is passed as an argument, the Linux argument limit applies.
    PROMPT_NO_ARGV = True
    TRANSITORIO: re.Pattern | None = None

    def __init__(self, cfg: ProviderConfig):
        self.cfg = cfg
        self._sem = asyncio.Semaphore(max(1, cfg.concorrencia))
        self._ritmo = asyncio.Lock()
        self._proximo = 0.0

    # --- implemented by each CLI ---------------------------------------------------

    def comando(self, prompt: str, modelo: str, json_schema: dict | None) -> Comando:
        raise NotImplementedError

    def interpretar(self, rc: int | None, out: str, err: str) -> Resultado:
        raise NotImplementedError

    async def modelos(self) -> list[str]:
        return list(self.cfg.modelos)

    # --- comum ---------------------------------------------------------------------

    def disponivel(self) -> bool:
        return self.cfg.ativo and shutil.which(self.cfg.bin) is not None

    def erro(self, mensagem: str) -> ErroCli:
        """Classify the failure: transient (503), unknown model (404), quota (429), or
        general failure (502)."""
        if self.TRANSITORIO is not None and self.TRANSITORIO.search(mensagem):
            return ErroCli(503, mensagem, transitorio=True)
        if _MODELO_INEXISTENTE.search(mensagem):
            return ErroCli(404, mensagem)
        if _COTA.search(mensagem):
            return ErroCli(429, mensagem, transitorio=True)
        return ErroCli(502, mensagem)

    async def _aguardar_vez(self) -> None:
        """Minimum interval between process starts (also used for quota pauses)."""
        async with self._ritmo:
            agora = time.monotonic()
            inicio = max(agora, self._proximo)
            self._proximo = inicio + self.cfg.intervalo_s
        if inicio > agora:
            await asyncio.sleep(inicio - agora)

    async def _pausar(self, segundos: float) -> None:
        """Do not start another process for this CLI for ``seconds``."""
        async with self._ritmo:
            self._proximo = max(self._proximo, time.monotonic() + segundos)

    async def executar(
        self, prompt: str, modelo: str, json_schema: dict | None = None
    ) -> Resultado:
        if not self.cfg.ativo:
            raise ErroCli(503, f"Provedor {self.nome} desligado ({self.nome.upper()}_ATIVO=0).")
        if self.PROMPT_NO_ARGV and len(prompt.encode()) > MAX_PROMPT_BYTES:
            raise ErroCli(413, f"Prompt exceeds {MAX_PROMPT_BYTES} bytes.")
        cmd = self.comando(prompt, modelo, json_schema)
        for n in range(self.cfg.tentativas + 1):
            try:
                return await self._executar(cmd)
            except ErroCli as err:
                if not err.transitorio or n == self.cfg.tentativas:
                    raise
                espera = self.ESPERA_TRANSITORIO_S * 2**n
                if err.status_http == 429:
                    espera = max(espera, self.ESPERA_COTA_S)
                await self._pausar(espera)
                logger.info(
                    "%s: %s, nova tentativa em %.0f s (%d/%d): %s",
                    self.nome,
                    "quota" if err.status_http == 429 else "transient error",
                    espera, n + 1, self.cfg.tentativas, resumo(err.mensagem, 200),
                )
        raise AssertionError("unreachable")

    async def _executar(self, cmd: Comando) -> Resultado:
        async with self._sem:
            await self._aguardar_vez()
            # Empty directory: the agent has no files to read or modify.
            with tempfile.TemporaryDirectory(prefix="llm-cli-") as cwd:
                # Files are in cwd, so the command refers to them by relative path.
                for nome, conteudo in cmd.arquivos.items():
                    Path(cwd, nome).write_text(conteudo, encoding="utf-8")
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *cmd.argv,
                        cwd=cwd,
                        stdin=asyncio.subprocess.PIPE if cmd.stdin is not None else asyncio.subprocess.DEVNULL,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        env={**os.environ, "NO_COLOR": "1"},
                    )
                except FileNotFoundError as err:
                    raise ErroCli(503, f"{self.nome} not found: {self.cfg.bin}") from err
                entrada = cmd.stdin.encode() if cmd.stdin is not None else None
                try:
                    out, err = await asyncio.wait_for(
                        proc.communicate(entrada), timeout=self.cfg.timeout_s + self.FOLGA_S
                    )
                except asyncio.TimeoutError as exc:
                    proc.kill()
                    await proc.wait()
                    raise ErroCli(504, f"{self.nome} passou de {self.cfg.timeout_s:.0f} s.") from exc
        return self.interpretar(
            proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")
        )
