"""Mensagens da OpenAI → prompt único do agy, e extração do JSON da resposta."""

from __future__ import annotations

import json
import re
from typing import Any

INSTRUCAO_JSON = (
    "Responda SOMENTE com um objeto JSON válido, sem markdown, sem cercas de "
    "código e sem texto antes ou depois."
)
_ROTULOS = {"user": "Usuário", "assistant": "Assistente", "tool": "Ferramenta"}


def _texto(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    # Formato em partes: [{"type": "text", "text": "..."}, ...]
    return "\n".join(
        p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
    )


def montar(messages: list[dict], json_mode: bool) -> str:
    """System no topo; o resto vira transcrição, terminando na última mensagem."""
    sistema = [_texto(m.get("content")) for m in messages if m["role"] in ("system", "developer")]
    conversa = [m for m in messages if m["role"] not in ("system", "developer")]
    partes = []
    if sistema:
        partes.append("\n\n".join(sistema))
    if len(conversa) == 1 and conversa[0]["role"] == "user":
        partes.append(_texto(conversa[0].get("content")))
    else:
        partes.append(
            "\n\n".join(
                f"### {_ROTULOS.get(m['role'], m['role'])}\n{_texto(m.get('content'))}"
                for m in conversa
            )
        )
        partes.append("Responda à última mensagem do Usuário.")
    if json_mode:
        partes.append(INSTRUCAO_JSON)
    return "\n\n".join(p for p in partes if p)


def extrair_json(texto: str) -> str | None:
    """Devolve o objeto JSON da resposta (sem cercas markdown), ou None."""
    t = texto.strip()
    cerca = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
    if cerca:
        t = cerca.group(1).strip()
    try:
        if isinstance(json.loads(t), dict):
            return t
    except ValueError:
        pass
    inicio = t.find("{")
    while inicio != -1:
        try:
            obj, fim = json.JSONDecoder().raw_decode(t, inicio)
        except ValueError:
            inicio = t.find("{", inicio + 1)
            continue
        if isinstance(obj, dict):
            return t[inicio:fim]
        inicio = t.find("{", fim)
    return None
