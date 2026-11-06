# agy-openai-api

API compatível com a OpenAI (`POST /v1/chat/completions`) que responde chamando o **Antigravity CLI** (`agy -p`). Serve para usar os créditos do `agy` em qualquer código que já fala com a OpenAI ou com o LiteLLM, como os relatórios do health score, sem mudar o cliente.

## Como subir

```bash
uv sync
cp .env.example .env   # opcional
uv run agy-openai-api  # http://127.0.0.1:8787
```

O `agy` precisa estar instalado e logado na máquina: confira com `agy models`. A API lê o `.env` da raiz do projeto ao subir. Uma variável já exportada no shell ganha do `.env`.

| Variável | Padrão | O que é |
|---|---|---|
| `AGY_BIN` | `agy` | executável do CLI |
| `AGY_API_KEY` | (vazia) | se definida, exige `Authorization: Bearer <chave>` |
| `AGY_CONCORRENCIA` | `2` | chamadas ao `agy` em paralelo |
| `AGY_INTERVALO_S` | `5` | segundos, no mínimo, entre o início de dois processos do `agy` |
| `AGY_TENTATIVAS` | `3` | novas tentativas quando o `agy` recusa o modelo por engano (30, 60 e 120 s; a cota é por minuto, e sem ela o `agy` nem carrega a lista de modelos) ou estoura a cota (60 s). Nos dois casos, a pausa vale para todos os processos |
| `AGY_TIMEOUT_S` | `180` | `--print-timeout` de cada chamada (o processo morre 15 s depois) |
| `AGY_MODELO_PADRAO` | `gemini-3.7-flash-low` | quando o pedido não traz `model` |
| `HOST` / `PORT` | `127.0.0.1` / `8787` | onde escutar |

## Endpoints

- `POST /v1/chat/completions`:
  - aceita `model` (os ids do `agy models`, como `gemini-3.8-flash-low` ou `gemini-4-argon-medium`; o sufixo define o esforço), `messages` e `response_format` (`json_object` ou `json_schema`);
  - aceita e ignora `temperature`, `max_tokens`, `metadata` e outros campos. O `agy` não tem flags para eles;
  - não tem streaming.
- `GET /v1/models`: lista do `agy models`, com cache de 10 minutos.
- `GET /health`: diz se o `agy` está no PATH.

### Como funciona

- **Prompt único.** O `agy -p` recebe um prompt só. As mensagens `system` vão no topo. Uma conversa de uma mensagem vira o texto do usuário. Uma conversa mais longa vira uma transcrição (`### Usuário` / `### Assistente`).
- **Modo JSON.** Com `response_format`, o prompt pede "SOMENTE JSON". Na resposta, a API tira as cercas markdown e extrai o primeiro objeto. Se não achar JSON válido, refaz a chamada uma vez e, se falhar de novo, devolve 502. O `json_schema` também vai para o `--json-schema` do `agy`.
- **Isolamento.** Cada chamada roda com `--sandbox --disable-slash-commands`, num diretório temporário vazio.
- **Contagem de tokens.** O `usage` repassa o do `agy`:
  - `prompt_tokens` = `input_tokens` + `cache_read_tokens`;
  - `completion_tokens` = `output_tokens` + `thinking_tokens`.

  A entrada inclui ~6,4 mil tokens do system prompt do próprio agente em toda chamada.
- **Erros** no formato da OpenAI:
  - 401: chave errada;
  - 413: prompt acima de 120 kB, o limite de um argumento no Linux;
  - 429: cota ou limite, com `Retry-After: 60`, depois das `AGY_TENTATIVAS`. Cada processo do `agy` gasta a cota "Management Requests per minute per user" ao abrir. Por isso a API abre no máximo um processo a cada `AGY_INTERVALO_S` e, ao receber 429, para de abrir processos por 60 s (medido em 2026-11-06);
  - 502: falha do `agy` ou resposta sem JSON;
  - 503: `agy` não encontrado, ou recusou o modelo nas `AGY_TENTATIVAS` novas tentativas. Com 8 processos abrindo juntos, alguns não carregam a lista de modelos e respondem "model ... is not recognized" para um modelo válido (medido em 2026-11-06);
  - 504: timeout.

  O SDK da OpenAI repete sozinho os 429 e 5xx.
- **Log.** O log registra modelo, duração, tokens e status, nunca o conteúdo.

Medido em 2026-11-06: ~3–6 s por chamada com o `gemini-3.7-flash-low`, e 4 chamadas em paralelo sem perda de tempo.

## Uso no health score (relatórios)

No `.env` do `slb-health-score-package`:

```bash
RELATORIOS_LLM=1
RELATORIOS_LLM_PROVEDOR=litellm
LITELLM_API_BASE=http://127.0.0.1:8787/v1
LITELLM_API_KEY=<AGY_API_KEY, ou qualquer valor se ela estiver vazia>
LITELLM_MODEL_NAME=gemini-3.7-flash-low
```

O modelo entra no `fatos_hash`, então grave os experimentos no dev:

```bash
uv run --extra relatorios python -m health_score.relatorios \
  --origem sld-ai-health-score-dev.health_score_results \
  --destino sld-ai-health-score-dev.health_score_results_dev --limite 50 --gravar
```

**Atenção:** a entrada dos relatórios não leva cnpj, nome nem e-mail, mas leva dados de uso e risco dos clientes, e o `agy` os envia ao Google pela conta pessoal do Antigravity. Use só onde isso for permitido.

## Testes

```bash
uv run pytest
```

Os testes usam um `agy` falso (`tests/fake_agy.py`) e não chamam o CLI real.
