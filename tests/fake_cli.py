#!/usr/bin/env python3
"""Fake CLI for tests: imitates agy, claude, codex, or kiro (FAKE_CLI).

Behavior is controlled by FAKE_CLI_MODE; each call is appended (one JSON object per
line) to FAKE_CLI_LOG, with arguments, cwd, stdin, and files in cwd.
"""

import json
import os
import sys
import time

cli = os.environ["FAKE_CLI"]
args = sys.argv[1:]
stdin = None if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
log = os.environ.get("FAKE_CLI_LOG")
if log:
    arquivos = {n: open(n, encoding="utf-8").read() for n in os.listdir(".")}
    with open(log, "a", encoding="utf-8") as f:
        registro = {"cli": cli, "args": args, "cwd": os.getcwd(), "stdin": stdin, "arquivos": arquivos}
        f.write(json.dumps(registro) + "\n")

if cli == "agy" and args[:1] == ["models"]:
    print("Fetching available models...")
    print("model-a\tModel A")
    print("model-b\tModel B")
    sys.exit(0)

mode = os.environ.get("FAKE_CLI_MODE", "ok")


def contar():
    contador = os.environ["FAKE_CLI_CONTADOR"]
    n = int(open(contador).read()) if os.path.exists(contador) else 0
    open(contador, "w").write(str(n + 1))
    return n


def sucesso(resposta):
    if cli == "agy":
        print("warning: an unimportant message", file=sys.stderr)
        usage = {"input_tokens": 100, "output_tokens": 10, "thinking_tokens": 5, "cache_read_tokens": 20}
        print(json.dumps({"status": "SUCCESS", "response": resposta, "duration_seconds": 0.1, "usage": usage}))
    elif cli == "claude":
        usage = {"input_tokens": 2, "cache_creation_input_tokens": 80, "cache_read_input_tokens": 20, "output_tokens": 7}
        print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": resposta,
                          "duration_ms": 900, "api_error_status": None, "usage": usage}))
    elif cli == "codex":
        print(json.dumps({"type": "thread.started", "thread_id": "t"}))
        print(json.dumps({"type": "turn.started"}))
        print(json.dumps({"type": "item.completed", "item": {"id": "i0", "type": "error", "message": "warning"}}))
        print(json.dumps({"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": resposta}}))
        print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 300, "cached_input_tokens": 200, "output_tokens": 9}}))
    elif cli == "kiro":
        print("\x1b[33mWARNING: \x1b[0m--trust-tools arg ...", file=sys.stderr)
        sys.stdout.write("\x1b[38;5;141m> \x1b[0m" + resposta)
        print("\x1b[38;5;8m\n ▸ Credits: 0.04 • Time: 1s\n\x1b[0m", file=sys.stderr)


def falha(mensagem, status=None):
    if cli == "agy":
        print(json.dumps({"status": "FAILED", "error": mensagem}))
    elif cli == "claude":
        print(json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": mensagem,
                          "api_error_status": status}))
        sys.exit(1)
    elif cli == "codex":
        corpo = json.dumps({"type": "error", "status": status or 400, "error": {"message": mensagem, "code": "x"}})
        print(json.dumps({"type": "thread.started", "thread_id": "t"}))
        print(json.dumps({"type": "error", "message": corpo}))
        print(json.dumps({"type": "turn.failed", "error": {"message": corpo}}))
        sys.exit(1)
    elif cli == "kiro":
        print("\x1b[33mWARNING: \x1b[0mwarning", file=sys.stderr)
        print(f"error: {mensagem}", file=sys.stderr)
        sys.exit(1)


if mode == "ok":
    sucesso('{"summary": "ok"}\n')
elif mode == "texto":
    sucesso("hello")
elif mode == "cerca":
    sucesso('Here it is:\n```json\n{"summary": "fenced"}\n```')
elif mode == "invalido":
    sucesso("I cannot answer in JSON")
elif mode == "invalido_uma_vez":
    sucesso("garbage" if contar() == 0 else '{"summary": "second"}')
elif mode == "lento":
    time.sleep(10)
    sucesso("{}")
elif mode == "falha":
    falha("something went wrong")
elif mode == "cota":
    falha("RESOURCE_EXHAUSTED: quota exceeded", status=429)
elif mode == "lixo":
    print("panic: no JSON", file=sys.stderr)
    sys.exit(2)
elif mode == "modelo_transitorio":
    if contar() == 0:
        falha('invalid model selection (--model "x"): model x is not recognized as a known model or custom model in settings')
    else:
        sucesso('{"summary": "ok"}')
