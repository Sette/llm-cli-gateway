# llm-cli-gateway

An OpenAI-compatible API (`POST /v1/chat/completions`) that runs **on your machine** and responds by calling an installed and authenticated **agent CLI**: Antigravity (`agy`), Claude Code (`claude`), Codex (`codex`), or Kiro (`kiro-cli`).

> **Local development tool.** The gateway helps reduce development costs: instead of paying per token to an LLM API while writing, testing, and adjusting code that calls a model, point that code at `http://127.0.0.1:8787/v1` and use the credits and subscriptions you already have for the CLIs. It is **not** a production service, a network-facing service, or a shared service.

## What it is for

- Develop and test locally code that already speaks OpenAI or LiteLLM (prompts, JSON parsing, reporting pipelines) without changing the client: just change the base URL.
- Run experiments and compare models (Gemini, Claude, GPT…) using CLI subscriptions instead of a paid API key.
- Run small and medium batches of calls on your own machine, such as reports.

## One API, many clients

The gateway speaks the OpenAI `chat/completions` format, the de facto industry standard. Any tool that accepts an "OpenAI-compatible provider" with a custom base URL can use the CLIs on your machine without a plugin or adapter:

- **SDKs:** `openai` (Python and JS), with `base_url="http://127.0.0.1:8787/v1"`.
- **Frameworks:** LiteLLM (the `openai/` provider or `litellm` with `api_base`), LangChain (`ChatOpenAI(base_url=...)`), LlamaIndex, DSPy, pydantic-ai, and similar tools.
- **Personal assistants and agents**, such as [OpenClaw](https://openclaw.ai), which supports custom providers.
- **Scripts and `curl`**, for quickly testing a prompt.

A single endpoint provides access to several providers: change `model` (`agy/…`, `claude/…`, `codex/…`, `kiro/…`) to compare Gemini, Claude, and GPT in the same code.

### Example: OpenClaw

In `~/.openclaw/openclaw.json`, register the gateway as a provider in `models.providers` and enable the models in `agents.defaults.models`. The sketch below follows OpenClaw's custom provider format. Check the field names in the documentation for the version you use:

```json5
{
  models: {
    providers: {
      "llm-cli-gateway": {
        baseUrl: "http://127.0.0.1:8787/v1",
        apiKey: "<API_KEY, or any value if it is empty>",
        api: "openai-completions",
        models: [
          { id: "claude/sonnet", name: "Claude Sonnet (via CLI)" },
          { id: "agy/gemini-3.7-flash-low", name: "Gemini Flash (via agy)" }
        ]
      }
    }
  },
  agents: {
    defaults: {
      models: ["llm-cli-gateway/claude/sonnet", "llm-cli-gateway/agy/gemini-3.7-flash-low"]
    }
  }
}
```

**Limitations to know before connecting an agent:**

- **Emulated streaming.** `stream: true` works, but the full response arrives in one chunk after the CLI finishes. The client does not see text appear gradually.
- **No tool calling.** The `tools` field is ignored, so the model never returns `tool_calls`. This is enough for conversation, summarization, classification, and JSON responses. An agent that relies on tools (running commands, browsing, editing files) cannot use them through this provider.

## What it is not for

- **Production.** Each call starts a CLI process (seconds of latency and ~3–11k tokens of agent system prompt per call), streaming is emulated, and sampling parameters (`temperature`, `max_tokens`…) are ignored. Use the provider's API or hosted LiteLLM in production.
- **Shared servers.** Calls use the account logged in on the machine running the gateway. It therefore listens on `127.0.0.1` by default. Do not expose the port on a network or put it behind a public proxy, even with `API_KEY`.
- **Replacing an API key.** Each provider's terms of use limit what you can do with a subscription. Use the gateway for your own development work and check the terms for the CLI you use.

## Requirements

- Python 3.12+ and [uv](https://docs.astral.sh/uv/).
- At least one CLI installed, available on `PATH`, and logged into your account: `agy`, `claude`, `codex`, or `kiro-cli`. The gateway does not log in or store credentials; it uses the session already held by the CLI.

## Model routing

The CLI is selected from the model prefix:

| `model` | CLI called | Model passed to the CLI |
|---|---|---|
| `agy/gemini-3.7-flash-low` | `agy` | `gemini-3.7-flash-low` |
| `claude/sonnet` | `claude` | `sonnet` |
| `codex/gpt-5.6-luna` | `codex` | `gpt-5.6-luna` |
| `kiro/claude-haiku-4.5` | `kiro-cli` | `claude-haiku-4.5` |
| `gemini-3.7-flash-low` (no prefix) | `PROVEDOR_PADRAO` (`agy`) | `gemini-3.7-flash-low` |

The project was previously called `agy-openai-api`. Models without a prefix still use `agy`, and `AGY_API_KEY` and `AGY_MODELO_PADRAO` remain supported, so existing clients do not need to change.

## Start the server

```bash
uv sync
cp .env.example .env   # optional
uv run llm-cli-gateway  # http://127.0.0.1:8787
```

Any OpenAI client can now use `base_url="http://127.0.0.1:8787/v1"`.

Each CLI must be installed and logged in. Check with `agy models`, `claude -p hi`, `codex exec hi`, and `kiro-cli chat --no-interactive hi`. `GET /health` shows which ones are available. The API reads the project's root `.env` file on startup. Variables already exported in the shell take precedence over `.env`.

### Global variables

| Variable | Default | Description |
|---|---|---|
| `API_KEY` | (empty) | If set, requires `Authorization: Bearer <key>`. Also accepts the legacy name `AGY_API_KEY`. |
| `PROVEDOR_PADRAO` | `agy` | Provider used for a `model` without a prefix. |
| `MODELO_PADRAO` | `agy/gemini-3.7-flash-low` | Used when a request has no `model`. Also accepts `AGY_MODELO_PADRAO`. |
| `HOST` / `PORT` | `127.0.0.1` / `8787` | Listening address. Keep `127.0.0.1`: the gateway is for local use. |

### Per-CLI variables

Prefixes: `AGY_`, `CLAUDE_`, `CODEX_`, or `KIRO_`:

| Suffix | Default | Description |
|---|---|---|
| `_BIN` | `agy`, `claude`, `codex`, `kiro-cli` | Executable. |
| `_ATIVO` | `1` | Set to `0` to disable the CLI (requests return 503; it is omitted from `/v1/models`). |
| `_CONCORRENCIA` | `2` | Parallel processes per CLI. |
| `_INTERVALO_S` | `5` for agy, `0` for others | Minimum seconds between starting processes. |
| `_TENTATIVAS` | `3` for agy, `2` for others | Retries for transient errors or quota errors (see below). |
| `_TIMEOUT_S` | `180` | Maximum time per call (the process is killed 15 seconds later). |
| `_MODELOS` | See `config.py` | Comma-separated list for `/v1/models`. For agy, used only if `agy models` fails. |

## Endpoints

- `POST /v1/chat/completions`:
  - accepts `model` (see the table above), `messages`, and `response_format` (`json_object` or `json_schema`);
  - accepts and ignores `temperature`, `max_tokens`, `metadata`, and other fields. The CLIs have no flags for these;
  - returns `model` as it was provided in the request;
  - `stream: true` is emulated: the CLI returns the full response, which is sent in one SSE chunk (`chat.completion.chunk`), followed by `finish_reason` and `data: [DONE]`. With `stream_options.include_usage`, a final chunk contains `usage`. Errors are returned before streaming, with the normal HTTP status;
  - does not support tool calling: `tools` and `tool_choice` are ignored.
- `GET /v1/models`: models for each available CLI, with a prefix (`agy/…`, `claude/…`) and `owned_by` set to the CLI. The agy list comes from `agy models` and is cached for 10 minutes. Other lists come from `<CLI>_MODELOS`.
- `GET /health`: `{"providers": {"agy": true, "claude": true, ...}}`. Returns 200 if at least one CLI is available on `PATH` and enabled.

## The CLIs

All CLIs run without a shell, in an empty temporary directory, without write-capable tools or saved sessions.

| CLI | Command | Prompt | `usage` | `json_schema` |
|---|---|---|---|---|
| agy | `agy -p … --sandbox --disable-slash-commands --output-format json` | Argument (up to 120 kB) | `input + cache_read` / `output + thinking` | `--json-schema` |
| claude | `claude -p --output-format json --tools "" --no-session-persistence --strict-mcp-config --setting-sources ""` | stdin | `input + cache_read + cache_creation` / `output` | `--json-schema` (uses `structured_output`) |
| codex | `codex exec --json --sandbox read-only --ephemeral --skip-git-repo-check --ignore-rules -` | stdin | `input_tokens` (includes cache) / `output_tokens` | `--output-schema` (file in cwd). The schema must be strict (`additionalProperties: false`, all fields in `required`). |
| kiro | `kiro-cli chat --no-interactive --trust-tools= --wrap never -- …` | Argument (up to 120 kB) | Not reported (remains 0) | Prompt instruction only |

Notes:
- Claude does not use `--bare`, which requires `ANTHROPIC_API_KEY` and ignores subscription login. Without `--setting-sources`, user hooks, plugins, and `CLAUDE.md` are excluded.
- Each call includes the agent's own system prompt: ~6.4k tokens for agy, ~3.4k for Claude, and ~11k for Codex (measured on 2026-11-06).

## How it works

- **Single prompt.** CLIs receive one prompt. `system` messages go at the top. A one-message conversation becomes the user text. Longer conversations become a transcript (`### User` / `### Assistant`).
- **JSON mode.** With `response_format`, the prompt requests "JSON ONLY". In the response, the API removes Markdown fences and extracts the first object. If it cannot find valid JSON, it retries the call once and returns 502 if that also fails.
- **Errors** use the OpenAI format:
  - 400: model contains invalid characters or has an unknown prefix;
  - 401: incorrect key;
  - 404: the CLI does not recognize the model;
  - 413: prompt exceeds 120 kB (agy and kiro receive the prompt as an argument);
  - 429: quota or rate limit after `<CLI>_TENTATIVAS`, with `Retry-After`. On 429, the API stops starting processes for that CLI for 60 seconds;
  - 502: CLI failure or response without JSON;
  - 503: CLI missing or disabled, or a transient error after the configured retries;
  - 504: timeout.

  The OpenAI SDK retries 429 and 5xx responses automatically.
- **agy quota.** Each agy process consumes Google's "Management Requests per minute per user" quota when it starts. Therefore agy starts at most one process per `AGY_INTERVALO_S`. When 8 processes start together, some may reject a valid model ("model ... is not recognized"); the API treats this as transient and retries after 30, 60, and 120 seconds (measured on 2026-11-06).
- **Logging.** Logs include the model, duration, token counts, and status, never the content.

Measured on 2026-11-06: ~3–6 seconds per call for `agy/gemini-3.7-flash-low` and ~3 seconds for `claude/haiku`.

## Tests

```bash
uv run pytest
```

Tests use a fake CLI (`tests/fake_cli.py`, which imitates each CLI's output) and do not call any real CLI.
