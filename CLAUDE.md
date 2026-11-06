# CLAUDE.md — agy-openai-api

API FastAPI compatível com a OpenAI (`/v1/chat/completions`, `/v1/models`) que repassa cada pedido ao Antigravity CLI (`agy -p --output-format json`). O README tem o uso e as variáveis.

- `src/agy_openai_api/agy.py`: subprocess assíncrono (sem shell, `--sandbox`, cwd temporário vazio), semáforo de concorrência, timeout e mapeamento de erros para HTTP. O formato da saída do `agy` está na docstring. Mudou a versão do `agy`? Confira se ainda bate.
- `prompt.py`: transforma as mensagens num prompt único e extrai o JSON da resposta.
- `main.py`: as rotas, o refazer único para JSON inválido e a auth por Bearer opcional.
- Não logue o conteúdo de prompts ou respostas: os clientes mandam dados de negócio.
- Testes: `uv run pytest`, com `tests/fake_agy.py` no lugar do CLI. Nunca chame o `agy` real nos testes.
- Primeiro cliente: os relatórios do `slb-health-score-package`, pelo provedor `litellm` (`LITELLM_API_BASE=http://127.0.0.1:8787/v1`).
