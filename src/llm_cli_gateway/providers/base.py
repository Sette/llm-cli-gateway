"""O que é comum a todos os CLIs: subprocess, ritmo, novas tentativas, timeout e erros.

Cada CLI é uma subclasse de :class:`CliProvider` que só diz como montar o comando
(:meth:`comando`) e como ler a saída (:meth:`interpretar`).
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

# Um argumento no Linux tem no máximo 128 KiB (MAX_ARG_STRLEN).
MAX_PROMPT_BYTES = 120_000
_COTA = re.compile(
    r"quota|rate.?limit|resource.?exhausted|too many requests|usage limit|\b429\b", re.I
)
# Modelo que o CLI não conhece (claude, codex, kiro): 404, como a OpenAI. O agy
# recusa modelo válido por engano e trata isso antes, como transitório.
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
    # Já normalizado: entrada = prompt (com cache), saída = resposta (com raciocínio).
    entrada: int = 0
    saida: int = 0
    duracao_s: float = 0.0


@dataclass
class Comando:
    argv: list[str]
    stdin: str | None = None
    # Arquivos que o comando lê (ex.: o schema do codex), criados no cwd temporário.
    arquivos: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderConfig:
    bin: str
    ativo: bool = True
    concorrencia: int = 2
    timeout_s: float = 180.0
    intervalo_s: float = 0.0
    tentativas: int = 2
    # Lista fixa para o /v1/models (o agy lista pelo próprio CLI).
    modelos: tuple[str, ...] = ()


def resumo(texto: str, limite: int = 500) -> str:
    texto = " ".join(sem_ansi(texto).split())
    return texto if len(texto) <= limite else texto[:limite] + "…"


def sem_ansi(texto: str) -> str:
    return _ANSI.sub("", texto)


class CliProvider:
    nome = ""
    # Folga sobre o timeout do próprio CLI antes de matar o processo.
    FOLGA_S = 15.0
    # Espera antes de repetir um erro transitório (dobra a cada tentativa).
    ESPERA_TRANSITORIO_S = 30.0
    # Cota: a pausa vale para todos os processos deste CLI, não só para o pedido que falhou.
    ESPERA_COTA_S = 60.0
    # O prompt vai como argumento? Então vale o limite do Linux.
    PROMPT_NO_ARGV = True
    TRANSITORIO: re.Pattern | None = None

    def __init__(self, cfg: ProviderConfig):
        self.cfg = cfg
        self._sem = asyncio.Semaphore(max(1, cfg.concorrencia))
        self._ritmo = asyncio.Lock()
        self._proximo = 0.0

    # --- o que cada CLI implementa -------------------------------------------------

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
        """Classifica a falha: transitório (503), modelo inexistente (404), cota (429) ou
        falha (502)."""
        if self.TRANSITORIO is not None and self.TRANSITORIO.search(mensagem):
            return ErroCli(503, mensagem, transitorio=True)
        if _MODELO_INEXISTENTE.search(mensagem):
            return ErroCli(404, mensagem)
        if _COTA.search(mensagem):
            return ErroCli(429, mensagem, transitorio=True)
        return ErroCli(502, mensagem)

    async def _aguardar_vez(self) -> None:
        """Intervalo mínimo entre o início de dois processos (e a pausa da cota)."""
        async with self._ritmo:
            agora = time.monotonic()
            inicio = max(agora, self._proximo)
            self._proximo = inicio + self.cfg.intervalo_s
        if inicio > agora:
            await asyncio.sleep(inicio - agora)

    async def _pausar(self, segundos: float) -> None:
        """Nenhum processo novo deste CLI abre nos próximos ``segundos``."""
        async with self._ritmo:
            self._proximo = max(self._proximo, time.monotonic() + segundos)

    async def executar(
        self, prompt: str, modelo: str, json_schema: dict | None = None
    ) -> Resultado:
        if not self.cfg.ativo:
            raise ErroCli(503, f"Provedor {self.nome} desligado ({self.nome.upper()}_ATIVO=0).")
        if self.PROMPT_NO_ARGV and len(prompt.encode()) > MAX_PROMPT_BYTES:
            raise ErroCli(413, f"Prompt com mais de {MAX_PROMPT_BYTES} bytes.")
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
                    "cota" if err.status_http == 429 else "erro transitório",
                    espera, n + 1, self.cfg.tentativas, resumo(err.mensagem, 200),
                )
        raise AssertionError("inalcançável")

    async def _executar(self, cmd: Comando) -> Resultado:
        async with self._sem:
            await self._aguardar_vez()
            # Diretório vazio: o agente não tem arquivo nenhum para ler ou mexer.
            with tempfile.TemporaryDirectory(prefix="llm-cli-") as cwd:
                # Os arquivos ficam no cwd: o comando os cita pelo caminho relativo.
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
                    raise ErroCli(503, f"{self.nome} não encontrado: {self.cfg.bin}") from err
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
