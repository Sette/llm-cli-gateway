# CLAUDE.md — llm-cli-gateway

FastAPI application compatible with OpenAI (`/v1/chat/completions`, `/v1/models`) that forwards each request to an agent CLI: `agy`, `claude`, `codex`, or `kiro-cli`. The provider is selected from the model prefix (`claude/sonnet`). Without a prefix, requests go to `PROVEDOR_PADRAO` (`agy`). See the README for usage and environment variables. The project was previously called `agy-openai-api`.

This is a local development tool for using CLI subscriptions instead of a paid API while developing and testing. It is not for production or network exposure: do not add deployment, multi-user, or default bind settings outside `127.0.0.1`.

- `src/llm_cli_gateway/providers/base.py`: behavior shared by CLIs. Async subprocess (no shell, empty temporary cwd, prompt via argv or stdin), semaphore, process interval, quota pause, retries, timeout, and HTTP error classification.
- `providers/<cli>.py`: only `command()` and `parse()` (plus `models()` in agy). Each module's docstring records the CLI output format measured for a specific version. When the CLI version changes, verify that the format still matches.
- New CLI: add a module in `providers/`, register it in `providers.CLASSES` and `config.PADROES`, and add its output format to `tests/fake_cli.py`.
- `prompt.py`: turns messages into a single prompt and extracts JSON from the response.
- `main.py`: routes, prefix-based routing, one retry for invalid JSON, emulated streaming (`_sse`, full response in one chunk), and optional Bearer authentication.
- `config.py`: global and `<CLI>_*` variables. `AGY_API_KEY` and `AGY_MODELO_PADRAO` remain supported.
- Isolation is required: no CLI may receive write tools, a shell, or access to user settings, MCP, or sessions.
- Never log prompt or response content: clients send business data.
- Tests: `uv run pytest`, using `tests/fake_cli.py` in place of the CLIs. Never invoke a real CLI in tests.
- First client: reports from `slb-health-score-package`, through the `litellm` provider (`LITELLM_API_BASE=http://127.0.0.1:8787/v1`).
