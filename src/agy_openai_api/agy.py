"""Executa o ``agy -p`` (print mode) e interpreta a saída ``--output-format json``.

Saída de sucesso (medida em 2026-11-06)::

    {"conversation_id": "...", "status": "SUCCESS", "response": "...",
     "duration_seconds": 3.9, "num_turns": 1,
     "usage": {"input_tokens": 6402, "output_tokens": 22, "thinking_tokens": 0,
               "cache_read_tokens": 0, "total_tokens": 6424}}
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
import time
from dataclasses import dataclass, field

logger = logging.getLogger("agy_openai_api")

# Um argumento no Linux tem no máximo 128 KiB (MAX_ARG_STRLEN).
MAX_PROMPT_BYTES = 120_000
_COTA = re.compile(r"quota|rate.?limit|resource.?exhausted|too many requests|\b429\b", re.I)
# Com vários agy abrindo juntos, alguns não carregam a lista de modelos e recusam um
# modelo que funciona (medido em 2026-11-06, 8 em paralelo). Passa ao tentar de novo.
_TRANSITORIO = re.compile(r"not recognized as a known model|invalid model selection", re.I)


class AgyErro(Exception):
    def __init__(self, status_http: int, mensagem: str, transitorio: bool = False):
        super().__init__(mensagem)
        self.status_http = status_http
        self.mensagem = mensagem
        self.transitorio = transitorio


@dataclass
class Resultado:
    texto: str
    usage: dict = field(default_factory=dict)
    duracao_s: float = 0.0


def _resumo(texto: str, limite: int = 500) -> str:
    texto = " ".join(texto.split())
    return texto if len(texto) <= limite else texto[:limite] + "…"


def _erro(mensagem: str) -> AgyErro:
    if _TRANSITORIO.search(mensagem):
        return AgyErro(503, mensagem, transitorio=True)
    if _COTA.search(mensagem):
        return AgyErro(429, mensagem, transitorio=True)
    return AgyErro(502, mensagem)


class Agy:
    # Folga sobre o --print-timeout antes de matar o processo.
    FOLGA_S = 15.0
    # Espera antes de repetir um erro transitório (dobra a cada tentativa).
    # A cota do Google é por minuto, e sem ela o agy nem carrega a lista de modelos:
    # esperar menos de um minuto só gasta mais cota.
    ESPERA_TRANSITORIO_S = 30.0
    # Cota do Google (ex.: "Management Requests per minute per user"): o próprio erro
    # pede um minuto. Cada processo do agy gasta essa cota ao abrir, então a pausa vale
    # para todos os processos, não só para o pedido que falhou.
    ESPERA_COTA_S = 60.0

    def __init__(
        self,
        agy_bin: str,
        concorrencia: int,
        timeout_s: float,
        intervalo_s: float = 0.0,
        tentativas: int = 2,
    ):
        self.agy_bin = agy_bin
        self.timeout_s = timeout_s
        self.intervalo_s = intervalo_s
        self.tentativas = tentativas
        self._sem = asyncio.Semaphore(concorrencia)
        self._ritmo = asyncio.Lock()
        self._proximo = 0.0

    async def _aguardar_vez(self) -> None:
        """Intervalo mínimo entre o início de dois processos do agy (e a pausa da cota)."""
        async with self._ritmo:
            agora = time.monotonic()
            inicio = max(agora, self._proximo)
            self._proximo = inicio + self.intervalo_s
        if inicio > agora:
            await asyncio.sleep(inicio - agora)

    def comando(self, prompt: str, modelo: str, json_schema: dict | None) -> list[str]:
        cmd = [
            self.agy_bin,
            "-p",
            prompt,
            "--model",
            modelo,
            "--sandbox",
            "--disable-slash-commands",
            "--output-format",
            "json",
            "--print-timeout",
            f"{int(self.timeout_s)}s",
        ]
        if json_schema is not None:
            cmd += ["--json-schema", json.dumps(json_schema, ensure_ascii=False)]
        return cmd

    async def executar(
        self, prompt: str, modelo: str, json_schema: dict | None = None
    ) -> Resultado:
        if len(prompt.encode()) > MAX_PROMPT_BYTES:
            raise AgyErro(413, f"Prompt com mais de {MAX_PROMPT_BYTES} bytes.")
        cmd = self.comando(prompt, modelo, json_schema)
        for n in range(self.tentativas + 1):
            try:
                return await self._executar(cmd)
            except AgyErro as err:
                if not err.transitorio or n == self.tentativas:
                    raise
                espera = self.ESPERA_TRANSITORIO_S * 2**n
                if err.status_http == 429:
                    espera = max(espera, self.ESPERA_COTA_S)
                # O "modelo não reconhecido" também aparece quando a cota aperta:
                # pausa todos os processos, não só este pedido.
                await self._pausar(espera)
                logger.info(
                    "agy: %s, nova tentativa em %.0f s (%d/%d): %s",
                    "cota" if err.status_http == 429 else "erro transitório",
                    espera, n + 1, self.tentativas, _resumo(err.mensagem, 200),
                )
        raise AssertionError("inalcançável")

    async def _pausar(self, segundos: float) -> None:
        """Nenhum processo novo do agy abre nos próximos ``segundos``."""
        async with self._ritmo:
            self._proximo = max(self._proximo, time.monotonic() + segundos)

    async def _executar(self, cmd: list[str]) -> Resultado:
        async with self._sem:
            await self._aguardar_vez()
            # Diretório vazio: o agente não tem arquivo nenhum para ler ou mexer.
            with tempfile.TemporaryDirectory(prefix="agy-api-") as cwd:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        cwd=cwd,
                        stdin=asyncio.subprocess.DEVNULL,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                except FileNotFoundError as err:
                    raise AgyErro(503, f"agy não encontrado: {self.agy_bin}") from err
                try:
                    out, err = await asyncio.wait_for(
                        proc.communicate(), timeout=self.timeout_s + self.FOLGA_S
                    )
                except asyncio.TimeoutError as exc:
                    proc.kill()
                    await proc.wait()
                    raise AgyErro(504, f"agy passou de {self.timeout_s:.0f} s.") from exc
        return self._interpretar(proc.returncode, out.decode(errors="replace"), err.decode(errors="replace"))

    @staticmethod
    def _interpretar(rc: int | None, out: str, err: str) -> Resultado:
        # A saída pode ter avisos antes do JSON (ex.: "warning: ...").
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
            raise _erro(f"Saída do agy não é JSON (rc={rc}): {_resumo(err or out)}")
        status = str(dados.get("status", ""))
        if status.upper() == "TIMEOUT":
            raise AgyErro(504, "agy: print-timeout atingido.")
        if status.upper() != "SUCCESS":
            detalhe = dados.get("error") or dados.get("message") or dados.get("response") or err
            raise _erro(f"agy status={status}: {_resumo(str(detalhe))}")
        return Resultado(
            texto=str(dados.get("response") or ""),
            usage=dados.get("usage") or {},
            duracao_s=float(dados.get("duration_seconds") or 0),
        )

    async def modelos(self) -> list[str]:
        proc = await asyncio.create_subprocess_exec(
            self.agy_bin,
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
        return ids
