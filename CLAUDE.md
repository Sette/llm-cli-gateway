# CLAUDE.md — llm-cli-gateway

API FastAPI compatível com a OpenAI (`/v1/chat/completions`, `/v1/models`) que repassa cada pedido a um CLI de agente: `agy`, `claude`, `codex` ou `kiro-cli`. O provedor sai do prefixo do modelo (`claude/sonnet`). Sem prefixo, vai para o `PROVEDOR_PADRAO` (`agy`). O README tem o uso e as variáveis. Antes se chamava `agy-openai-api`.

É uma ferramenta de desenvolvimento local, para gastar as assinaturas dos CLIs em vez de API paga enquanto se desenvolve e testa. Não é para produção nem para expor na rede: não adicione recursos nessa direção (deploy, multiusuário, bind padrão fora de `127.0.0.1`).

- `src/llm_cli_gateway/providers/base.py`: o que é comum aos CLIs. Subprocess assíncrono (sem shell, cwd temporário vazio, prompt por argv ou stdin), semáforo, intervalo entre processos, pausa de cota, novas tentativas, timeout e a classificação de erros para HTTP.
- `providers/<cli>.py`: só `comando()` e `interpretar()` (mais `modelos()` no agy). O formato da saída de cada CLI está na docstring do módulo, medido numa versão. Mudou a versão do CLI? Confira se ainda bate.
- CLI novo: um módulo em `providers/`, a entrada em `providers.CLASSES` e em `config.PADROES`, e o formato no `tests/fake_cli.py`.
- `prompt.py`: transforma as mensagens num prompt único e extrai o JSON da resposta.
- `main.py`: as rotas, o roteamento pelo prefixo, o refazer único para JSON inválido, o streaming emulado (`_sse`, resposta inteira num chunk) e a auth por Bearer opcional.
- `config.py`: variáveis globais e `<CLI>_*`. `AGY_API_KEY` e `AGY_MODELO_PADRAO` seguem aceitos.
- Isolamento é requisito: nenhum CLI pode ganhar ferramenta de escrita, shell ou acesso às settings, MCP e sessões do usuário.
- Não logue o conteúdo de prompts ou respostas: os clientes mandam dados de negócio.
- Testes: `uv run pytest`, com `tests/fake_cli.py` no lugar dos CLIs. Nunca chame um CLI real nos testes.
- Primeiro cliente: os relatórios do `slb-health-score-package`, pelo provedor `litellm` (`LITELLM_API_BASE=http://127.0.0.1:8787/v1`).
