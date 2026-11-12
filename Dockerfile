FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

# Stage de testes (ex.: docker build --target test .)
FROM base AS test
COPY tests ./tests
RUN uv sync --frozen
CMD ["uv", "run", "pytest"]

# Stage final de execução
FROM base AS runtime
RUN uv sync --frozen --no-dev --no-editable \
    && useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app

ENV PATH="/app/.venv/bin:${PATH}"

USER appuser
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; p = os.getenv('PORT', '8787'); urllib.request.urlopen(f'http://127.0.0.1:{p}/health', timeout=3)" || exit 1

CMD ["llm-cli-gateway"]
