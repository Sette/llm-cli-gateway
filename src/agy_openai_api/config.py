"""Configuração por variáveis de ambiente (lidas a cada uso, para os testes)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    agy_bin: str
    api_key: str | None
    concorrencia: int
    timeout_s: float
    modelo_padrao: str
    host: str
    port: int
    intervalo_s: float = 0.0
    tentativas: int = 2


def load() -> Config:
    return Config(
        agy_bin=os.getenv("AGY_BIN", "agy"),
        api_key=os.getenv("AGY_API_KEY") or None,
        concorrencia=int(os.getenv("AGY_CONCORRENCIA", "2")),
        timeout_s=float(os.getenv("AGY_TIMEOUT_S", "180")),
        modelo_padrao=os.getenv("AGY_MODELO_PADRAO", "gemini-3.7-flash-low"),
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8787")),
        intervalo_s=float(os.getenv("AGY_INTERVALO_S", "5")),
        tentativas=int(os.getenv("AGY_TENTATIVAS", "3")),
    )
