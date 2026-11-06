"""Os CLIs suportados. Um CLI novo é um módulo aqui mais a entrada em ``CLASSES``."""

from __future__ import annotations

from .agy import AgyProvider
from .base import CliProvider, ErroCli, ProviderConfig, Resultado
from .claude import ClaudeProvider
from .codex import CodexProvider
from .kiro import KiroProvider

CLASSES: dict[str, type[CliProvider]] = {
    "agy": AgyProvider,
    "claude": ClaudeProvider,
    "codex": CodexProvider,
    "kiro": KiroProvider,
}


def construir(configs: dict[str, ProviderConfig]) -> dict[str, CliProvider]:
    return {nome: CLASSES[nome](cfg) for nome, cfg in configs.items()}


def separar(modelo: str, padrao: str) -> tuple[str, str]:
    """``"claude/sonnet"`` → ``("claude", "sonnet")``; sem prefixo, usa o provedor padrão."""
    if "/" in modelo:
        provedor, _, nome = modelo.partition("/")
        return provedor, nome
    return padrao, modelo


__all__ = [
    "CLASSES",
    "CliProvider",
    "ErroCli",
    "ProviderConfig",
    "Resultado",
    "construir",
    "separar",
]
