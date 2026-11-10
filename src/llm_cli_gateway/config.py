"""Environment variable configuration (read on each use for testing).

Globais: ``API_KEY``, ``PROVEDOR_PADRAO``, ``MODELO_PADRAO``, ``HOST``, ``PORT``.
Por CLI (prefixo ``AGY_``, ``CLAUDE_``, ``CODEX_``, ``KIRO_``): ``_BIN``, ``_ATIVO``,
``_CONCORRENCIA``, ``_INTERVALO_S``, ``_TENTATIVAS``, ``_TIMEOUT_S``, ``_MODELOS``.
``AGY_API_KEY`` and ``AGY_MODELO_PADRAO`` (names from agy-openai-api) remain supported.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .providers import ProviderConfig

# Defaults for each CLI. agy values are based on measurements from 2026-11-06 (per-minute quota).
PADROES: dict[str, dict] = {
    "agy": {
        "bin": "agy",
        "concorrencia": 2,
        "intervalo_s": 5.0,
        "tentativas": 3,
        "modelos": "gemini-3.7-flash-low",
    },
    "claude": {"bin": "claude", "modelos": "haiku,sonnet,opus"},
    "codex": {"bin": "codex", "modelos": "gpt-6-luna,gpt-5.6-terra,gpt-5.6-luna"},
    "kiro": {
        "bin": "kiro-cli",
        "modelos": "auto,claude-sonnet-4.5,claude-haiku-4.5,deepseek-3.2,glm-5,qwen3-coder-next",
    },
}


@dataclass(frozen=True)
class Config:
    providers: dict[str, ProviderConfig]
    api_key: str | None = None
    provedor_padrao: str = "agy"
    modelo_padrao: str = "agy/gemini-3.7-flash-low"
    host: str = "127.0.0.1"
    port: int = 8787


def _bool(valor: str) -> bool:
    return valor.strip().lower() not in ("0", "false", "no", "off", "")


def _provider(nome: str) -> ProviderConfig:
    p = PADROES[nome]
    pre = nome.upper() + "_"

    def env(chave: str, padrao) -> str:
        return os.getenv(pre + chave, str(padrao))

    return ProviderConfig(
        bin=env("BIN", p["bin"]),
        ativo=_bool(env("ATIVO", "1")),
        concorrencia=int(env("CONCORRENCIA", p.get("concorrencia", 2))),
        timeout_s=float(env("TIMEOUT_S", p.get("timeout_s", 180))),
        intervalo_s=float(env("INTERVALO_S", p.get("intervalo_s", 0))),
        tentativas=int(env("TENTATIVAS", p.get("tentativas", 2))),
        modelos=tuple(m.strip() for m in env("MODELOS", p["modelos"]).split(",") if m.strip()),
    )


def load() -> Config:
    return Config(
        providers={nome: _provider(nome) for nome in PADROES},
        api_key=os.getenv("API_KEY") or os.getenv("AGY_API_KEY") or None,
        provedor_padrao=os.getenv("PROVEDOR_PADRAO", "agy"),
        modelo_padrao=(
            os.getenv("MODELO_PADRAO") or os.getenv("AGY_MODELO_PADRAO") or "agy/gemini-3.7-flash-low"
        ),
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8787")),
    )
