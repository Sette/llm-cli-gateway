#!/usr/bin/env python3
"""agy falso para os testes. O comportamento vem de FAKE_AGY_MODE; os argumentos
de cada chamada são anexados (JSON por linha) em FAKE_AGY_LOG."""

import json
import os
import sys
import time

args = sys.argv[1:]
log = os.environ.get("FAKE_AGY_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"args": args, "cwd": os.getcwd()}) + "\n")

if args[:1] == ["models"]:
    print("Fetching available models...")
    print("modelo-a\tModelo A")
    print("modelo-b\tModelo B")
    sys.exit(0)

mode = os.environ.get("FAKE_AGY_MODE", "ok")
usage = {"input_tokens": 100, "output_tokens": 10, "thinking_tokens": 5, "cache_read_tokens": 20}


def sucesso(resposta):
    print("warning: algo sem importância", file=sys.stderr)
    print(json.dumps({"status": "SUCCESS", "response": resposta, "duration_seconds": 0.1, "usage": usage}))


if mode == "ok":
    sucesso('{"resumo": "ok"}\n')
elif mode == "texto":
    sucesso("olá")
elif mode == "cerca":
    sucesso('Aqui está:\n```json\n{"resumo": "cercado"}\n```')
elif mode == "invalido":
    sucesso("não sei responder em JSON")
elif mode == "invalido_uma_vez":
    contador = os.environ["FAKE_AGY_CONTADOR"]
    n = int(open(contador).read()) if os.path.exists(contador) else 0
    open(contador, "w").write(str(n + 1))
    sucesso("lixo" if n == 0 else '{"resumo": "segunda"}')
elif mode == "lento":
    time.sleep(10)
    sucesso("{}")
elif mode == "falha":
    print(json.dumps({"status": "FAILED", "error": "deu ruim"}))
elif mode == "cota":
    print(json.dumps({"status": "FAILED", "error": "RESOURCE_EXHAUSTED: quota exceeded"}))
elif mode == "lixo":
    print("panic: nada de JSON", file=sys.stderr)
    sys.exit(2)
elif mode == "modelo_transitorio":
    contador = os.environ["FAKE_AGY_CONTADOR"]
    n = int(open(contador).read()) if os.path.exists(contador) else 0
    open(contador, "w").write(str(n + 1))
    if n == 0:
        print(json.dumps({"status": "ERROR", "error": 'invalid model selection (--model "x"): model x is not recognized as a known model or custom model in settings'}))
    else:
        sucesso('{"resumo": "ok"}')
