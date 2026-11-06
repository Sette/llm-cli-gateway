# llm-cli-gateway

API compatível com a OpenAI (`POST /v1/chat/completions`) que responde chamando um **CLI de agente** já logado na máquina: Antigravity (`agy`), Claude Code (`claude`), Codex (`codex`) ou Kiro (`kiro-cli`). Serve para usar os créditos e as assinaturas desses CLIs em qualquer código que já fala com a OpenAI ou com o LiteLLM, como os relatórios do health score, sem mudar o cliente.

O CLI sai do prefixo do modelo:

| `model` | CLI chamado | modelo passado ao CLI |
|---|---|---|
| `agy/gemini-3.7-flash-low` | `agy` | `gemini-3.7-flash-low` |
| `claude/sonnet` | `claude` | `sonnet` |
| `codex/gpt-5.6-luna` | `codex` | `gpt-5.6-luna` |
| `kiro/claude-haiku-4.5` | `kiro-cli` | `claude-haiku-4.5` |
| `gemini-3.7-flash-low` (sem prefixo) | `PROVEDOR_PADRAO` (`agy`) | `gemini-3.7-flash-low` |

Antes se chamava `agy-openai-api`. Modelo sem prefixo continua indo para o `agy`, e as variáveis `AGY_API_KEY` e `AGY_MODELO_PADRAO` continuam valendo, então os clientes antigos não precisam mudar.

## Como subir

```bash
uv sync
cp .env.example .env   # opcional
uv run llm-cli-gateway  # http://127.0.0.1:8787
```

Cada CLI precisa estar instalado e logado: confira com `agy models`, `claude -p oi`, `codex exec oi` e `kiro-cli chat --no-interactive oi`. O `GET /health` mostra quais estão disponíveis. A API lê o `.env` da raiz do projeto ao subir. Uma variável já exportada no shell ganha do `.env`.

### Variáveis globais

| Variável | Padrão | O que é |
|---|---|---|
| `API_KEY` | (vazia) | se definida, exige `Authorization: Bearer <chave>`. Aceita `AGY_API_KEY` como nome antigo |
| `PROVEDOR_PADRAO` | `agy` | para onde vai um `model` sem prefixo |
| `MODELO_PADRAO` | `agy/gemini-3.7-flash-low` | quando o pedido não traz `model`. Aceita `AGY_MODELO_PADRAO` |
| `HOST` / `PORT` | `127.0.0.1` / `8787` | onde escutar |

### Variáveis por CLI

Prefixo `AGY_`, `CLAUDE_`, `CODEX_` ou `KIRO_`:

| Sufixo | Padrão | O que é |
|---|---|---|
| `_BIN` | `agy`, `claude`, `codex`, `kiro-cli` | executável |
| `_ATIVO` | `1` | `0` desliga o CLI (503 nas chamadas, fora do `/v1/models`) |
| `_CONCORRENCIA` | `2` | processos em paralelo, por CLI |
| `_INTERVALO_S` | `5` no agy, `0` nos outros | segundos, no mínimo, entre o início de dois processos |
| `_TENTATIVAS` | `3` no agy, `2` nos outros | novas tentativas em erro transitório ou cota (ver abaixo) |
| `_TIMEOUT_S` | `180` | tempo máximo por chamada (o processo morre 15 s depois) |
| `_MODELOS` | ver `config.py` | lista do `/v1/models`, separada por vírgula. No agy, só vale se o `agy models` falhar |

## Endpoints

- `POST /v1/chat/completions`:
  - aceita `model` (ver a tabela acima), `messages` e `response_format` (`json_object` ou `json_schema`);
  - aceita e ignora `temperature`, `max_tokens`, `metadata` e outros campos. Os CLIs não têm flags para eles;
  - devolve `model` como veio no pedido;
  - não tem streaming.
- `GET /v1/models`: os modelos de cada CLI disponível, com o prefixo (`agy/…`, `claude/…`), e `owned_by` = CLI. O do agy vem do `agy models`, com cache de 10 minutos. Os dos outros vêm de `<CLI>_MODELOS`.
- `GET /health`: `{"providers": {"agy": true, "claude": true, ...}}`. Responde 200 se ao menos um CLI estiver no PATH e ativo.

## Os CLIs

Todos rodam sem shell, num diretório temporário vazio, sem ferramentas que escrevam e sem guardar sessão.

| CLI | Comando | Prompt | `usage` | `json_schema` |
|---|---|---|---|---|
| agy | `agy -p … --sandbox --disable-slash-commands --output-format json` | argumento (até 120 kB) | `input + cache_read` / `output + thinking` | `--json-schema` |
| claude | `claude -p --output-format json --tools "" --no-session-persistence --strict-mcp-config --setting-sources ""` | stdin | `input + cache_read + cache_creation` / `output` | `--json-schema` (usa o `structured_output`) |
| codex | `codex exec --json --sandbox read-only --ephemeral --skip-git-repo-check --ignore-rules -` | stdin | `input_tokens` (já inclui o cache) / `output_tokens` | `--output-schema` (arquivo no cwd). O schema precisa ser estrito (`additionalProperties: false`, todos os campos em `required`) |
| kiro | `kiro-cli chat --no-interactive --trust-tools= --wrap never -- …` | argumento (até 120 kB) | não informa (fica 0) | só a instrução no prompt |

Notas:
- O `claude` não usa `--bare`, que exige `ANTHROPIC_API_KEY` e ignora o login da assinatura. Sem `--setting-sources`, os hooks, plugins e o CLAUDE.md do usuário ficam de fora.
- A entrada inclui o system prompt do próprio agente em toda chamada: ~6,4 mil tokens no agy, ~3,4 mil no claude e ~11 mil no codex (medido em 2026-11-06).

## Como funciona

- **Prompt único.** Os CLIs recebem um prompt só. As mensagens `system` vão no topo. Uma conversa de uma mensagem vira o texto do usuário. Uma conversa mais longa vira uma transcrição (`### Usuário` / `### Assistente`).
- **Modo JSON.** Com `response_format`, o prompt pede "SOMENTE JSON". Na resposta, a API tira as cercas markdown e extrai o primeiro objeto. Se não achar JSON válido, refaz a chamada uma vez e, se falhar de novo, devolve 502.
- **Erros** no formato da OpenAI:
  - 400: modelo com caracteres inválidos ou prefixo desconhecido;
  - 401: chave errada;
  - 404: o CLI não conhece o modelo;
  - 413: prompt acima de 120 kB (agy e kiro, que recebem o prompt como argumento);
  - 429: cota ou limite, com `Retry-After`, depois das `<CLI>_TENTATIVAS`. Ao receber 429, a API para de abrir processos daquele CLI por 60 s;
  - 502: falha do CLI ou resposta sem JSON;
  - 503: CLI não encontrado ou desligado, ou erro transitório nas `_TENTATIVAS` novas tentativas;
  - 504: timeout.

  O SDK da OpenAI repete sozinho os 429 e 5xx.
- **Cota do agy.** Cada processo do `agy` gasta a cota "Management Requests per minute per user" do Google ao abrir. Por isso o agy abre no máximo um processo a cada `AGY_INTERVALO_S`. Com 8 processos abrindo juntos, alguns recusam um modelo válido ("model ... is not recognized"): a API trata isso como transitório e repete depois de 30, 60 e 120 s (medido em 2026-11-06).
- **Log.** O log registra modelo, duração, tokens e status, nunca o conteúdo.

Medido em 2026-11-06, por chamada: ~3–6 s no `agy/gemini-3.7-flash-low` e ~3 s no `claude/haiku`.

## Uso no health score (relatórios)

No `.env` do `slb-health-score-package`:

```bash
RELATORIOS_LLM=1
RELATORIOS_LLM_PROVEDOR=litellm
LITELLM_API_BASE=http://127.0.0.1:8787/v1
LITELLM_API_KEY=<API_KEY, ou qualquer valor se ela estiver vazia>
LITELLM_MODEL_NAME=agy/gemini-3.7-flash-low   # ou claude/haiku, codex/gpt-5.6-luna...
```

O modelo entra no `fatos_hash`, então grave os experimentos no dev:

```bash
uv run --extra relatorios python -m health_score.relatorios \
  --origem sld-ai-health-score-dev.health_score_results \
  --destino sld-ai-health-score-dev.health_score_results_dev --limite 50 --gravar
```

**Atenção:** a entrada dos relatórios não leva cnpj, nome nem e-mail, mas leva dados de uso e risco dos clientes. Cada CLI os envia ao seu fornecedor pela conta logada na máquina: Google (agy), Anthropic (claude), OpenAI (codex) e AWS (kiro, que ainda pode rotear para outros modelos, como DeepSeek, GLM e Qwen). Use só onde isso for permitido.

## Testes

```bash
uv run pytest
```

Os testes usam um CLI falso (`tests/fake_cli.py`, que imita a saída de cada um) e não chamam nenhum CLI real.
