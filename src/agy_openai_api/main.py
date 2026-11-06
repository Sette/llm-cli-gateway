"""App FastAPI: /v1/chat/completions, /v1/models e /health sobre o agy."""

from __future__ import annotations

import logging
import re
import secrets
import shutil
import time
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from . import config as config_mod
from .agy import Agy, AgyErro
from .prompt import extrair_json, montar
from .schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    ChoiceMessage,
    Usage,
)

logger = logging.getLogger("agy_openai_api")
CACHE_MODELOS_S = 600
_MODELO_VALIDO = re.compile(r"[A-Za-z0-9._:-]{1,100}")


def _uso(usage: dict) -> tuple[int, int]:
    entrada = int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_tokens") or 0)
    saida = int(usage.get("output_tokens") or 0) + int(usage.get("thinking_tokens") or 0)
    return entrada, saida


def _erro_openai(status: int, mensagem: str) -> JSONResponse:
    tipo = {401: "authentication_error", 429: "rate_limit_error"}.get(status, "api_error")
    # O cliente (SDK da OpenAI, relatórios) espera o Retry-After antes de repetir.
    headers = {"Retry-After": str(int(Agy.ESPERA_COTA_S))} if status == 429 else None
    return JSONResponse(
        status_code=status,
        content={"error": {"message": mensagem, "type": tipo, "code": status}},
        headers=headers,
    )


def create_app(cfg: config_mod.Config | None = None) -> FastAPI:
    cfg = cfg or config_mod.load()
    agy = Agy(cfg.agy_bin, cfg.concorrencia, cfg.timeout_s, cfg.intervalo_s, cfg.tentativas)
    cache: dict = {"em": 0.0, "ids": []}
    app = FastAPI(title="agy-openai-api", version="0.1.0")

    def autenticar(authorization: str | None = Header(default=None)) -> None:
        if not cfg.api_key:
            return
        token = (authorization or "").removeprefix("Bearer ").strip()
        if not secrets.compare_digest(token, cfg.api_key):
            raise HTTPException(status_code=401, detail="API key inválida.")

    @app.exception_handler(HTTPException)
    async def _http(_req, exc: HTTPException):
        return _erro_openai(exc.status_code, str(exc.detail))

    @app.get("/health")
    async def health():
        ok = shutil.which(cfg.agy_bin) is not None
        return JSONResponse(
            status_code=200 if ok else 503,
            content={"status": "ok" if ok else "agy não encontrado", "agy": cfg.agy_bin},
        )

    @app.get("/v1/models", dependencies=[Depends(autenticar)])
    async def models():
        if time.monotonic() - cache["em"] > CACHE_MODELOS_S or not cache["ids"]:
            try:
                cache["ids"] = await agy.modelos()
                cache["em"] = time.monotonic()
            except Exception as err:  # pylint: disable=broad-except
                logger.warning("agy models falhou: %s", err)
        ids = cache["ids"] or [cfg.modelo_padrao]
        return {
            "object": "list",
            "data": [{"id": i, "object": "model", "created": 0, "owned_by": "agy"} for i in ids],
        }

    @app.post("/v1/chat/completions", dependencies=[Depends(autenticar)])
    async def chat_completions(req: ChatCompletionRequest):
        if req.stream:
            raise HTTPException(status_code=400, detail="stream=true não é suportado.")
        modelo = req.model or cfg.modelo_padrao
        if not _MODELO_VALIDO.fullmatch(modelo):
            # Ex.: comentário colado no valor do .env. O agy responderia "modelo não
            # reconhecido", que a API trata como transitório e repetiria por minutos.
            raise HTTPException(status_code=400, detail=f"Nome de modelo inválido: {modelo[:80]!r}")
        rf = req.response_format or {}
        tipo_rf = rf.get("type")
        json_mode = tipo_rf in ("json_object", "json_schema")
        schema = (rf.get("json_schema") or {}).get("schema") if tipo_rf == "json_schema" else None
        prompt = montar([m.model_dump() for m in req.messages], json_mode)

        entrada = saida = 0
        inicio = time.monotonic()
        texto = ""
        # JSON inválido: mais uma chamada antes de desistir.
        for tentativa in range(2 if json_mode else 1):
            try:
                res = await agy.executar(prompt, modelo, schema)
            except AgyErro as err:
                logger.warning(
                    "chat model=%s status=%d %.1fs: %s",
                    modelo, err.status_http, time.monotonic() - inicio, err.mensagem,
                )
                return _erro_openai(err.status_http, err.mensagem)
            e, s = _uso(res.usage)
            entrada, saida = entrada + e, saida + s
            texto = res.texto
            if not json_mode:
                break
            extraido = extrair_json(texto)
            if extraido is not None:
                texto = extraido
                break
            logger.info("chat model=%s: resposta sem JSON (tentativa %d)", modelo, tentativa + 1)
        else:
            logger.warning("chat model=%s status=502: JSON inválido duas vezes", modelo)
            return _erro_openai(502, f"Resposta sem JSON válido: {texto[:300]}")

        logger.info(
            "chat model=%s status=200 %.1fs tokens=%d+%d",
            modelo, time.monotonic() - inicio, entrada, saida,
        )
        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex}",
            created=int(time.time()),
            model=modelo,
            choices=[Choice(message=ChoiceMessage(content=texto))],
            usage=Usage(prompt_tokens=entrada, completion_tokens=saida, total_tokens=entrada + saida),
        )

    return app


def run() -> None:
    import uvicorn  # pylint: disable=import-outside-toplevel

    from pathlib import Path  # pylint: disable=import-outside-toplevel

    from dotenv import load_dotenv  # pylint: disable=import-outside-toplevel

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # O .env da raiz do projeto; variável já exportada no shell ganha dele.
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    cfg = config_mod.load()
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    run()
