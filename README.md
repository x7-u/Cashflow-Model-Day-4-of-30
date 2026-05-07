# Day 04. 13-Week Cash Flow Model.

![AI provider: DeepSeek V4](https://img.shields.io/badge/AI-DeepSeek_V4-2A6CC0?style=flat-square)
![Stack: Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![Local-only](https://img.shields.io/badge/Hosted-Local_only_(127.0.0.1:1004)-555555?style=flat-square)
![Status](https://img.shields.io/badge/Status-MVP_complete-16A34A?style=flat-square)

Rolling 13-week cash flow forecast with WACC-style discounting on the future receipts, a typed scenario engine that flexes weekly receipts and payments, and an AI commentary block that explains the resulting closing balance trajectory.

This is **Day 04 of a 30-day finance and AI portfolio sprint** where each
project is shipped end-to-end in a single day, runs locally on its own
loopback port, and integrates the AI in a way that is not cosmetic. The
series alternates between Claude (Days 1 to 3) and DeepSeek V4 (Days 4
onwards) with a deliberate provider switch documented in the README.

---

## AI provider

**This project uses the DeepSeek V4 API (OpenAI-compatible).**

- **Model**: DeepSeek V4 (via the OpenAI SDK pointed at DeepSeek's base URL).
- **Cost target**: around $0.0005 per scenario.
- **Why DeepSeek here**: Days 4 onwards of the 30-day series switched off Claude to DeepSeek V4 for cost. DeepSeek's chat endpoint is OpenAI-compatible (we use the openai SDK pointed at DeepSeek's base URL), JSON mode is reliable, and prefix caching on identical system prompts brings repeat calls down further. Roughly 5x to 15x cheaper than Claude Haiku 4.5 on JSON-shaped finance workloads.

The shared client is `shared/deepseek_client.py` and exposes `ask_deepseek_json_with_stats(prompt, system, max_tokens, model)`. It returns the parsed JSON plus a `CallResult` with token counts, cache-hit tokens, latency and cost in USD.

---

## What it does

Rolling 13-week cash flow forecast with WACC-style discounting on the future receipts, a typed scenario engine that flexes weekly receipts and payments, and an AI commentary block that explains the resulting closing balance trajectory.

The MVP is intentionally compact:

1. The user uploads a file (or picks a bundled sample).
2. The pipeline parses, validates and normalises the input.
3. The deterministic finance maths runs locally (no AI involved).
4. A single AI call writes the narrative around those numbers.
5. The web UI renders the result; Excel + PDF + CSV exports drop into `outputs/`.

Every analytical figure is computed by Python, not the LLM. The AI is
asked only to interpret and explain.

## Quickstart (Windows)

One-time setup, from the repo root:

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
notepad .env       :: paste your API key
```

Then run:

```bat
start.bat
```

A browser window opens at `http://127.0.0.1:1004/`.

## Quickstart (macOS / Linux)

```bash
python -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
$EDITOR .env       # paste your API key
chmod +x start.sh
./start.sh
```

## Environment variables

- `DEEPSEEK_API_KEY` -- Required. Get one at https://platform.deepseek.com/.
- `DEEPSEEK_MODEL_FAST` -- Optional override; deepseek-chat resolves to V4 latest.
- `DEEPSEEK_BASE_URL` -- Optional, only override if you proxy.

The `.env` file is git-ignored. **Never commit it.** A `.env.example` lives
next to it with placeholder values that you can copy.

## Stack

- Python 3.11+
- openpyxl, matplotlib, pandas, numpy, openai (DeepSeek client), flask
- System fonts only, no CDN dependencies, loopback only.

## File layout

```
day-04-cashflow-model/
  server.py            Flask web server (port 1004)
  main.py              CLI entry point
  pipeline.py          orchestrator
  shared/              vendored shared modules (config, AI client, etc.)
  static/              frontend CSS + JS + favicon
  templates/           Jinja2 HTML
  sample_data/         deterministic samples that round-trip the parser
  tests/               pytest suite
  outputs/             generated artefacts (gitignored)
  uploads/             user uploads (gitignored)
  logs/                rotating server log (gitignored)
  start.bat / start.sh launchers
  requirements.txt
  README.md (this file)
  .env.example         placeholders for the env vars above
  .gitignore
  LICENSE              MIT
```

## Running tests

```bat
.venv\Scripts\python.exe -m pytest
```

The tests do not call the AI provider; the LLM is stubbed where the
pipeline crosses the network.

## Security and privacy notes

- All processing is local. The server binds to `127.0.0.1` only; no
  inbound traffic is accepted from the network.
- The only outbound call is to the AI provider's API endpoint
  (`api.anthropic.com` for Claude or `api.deepseek.com` for DeepSeek).
- Uploaded files stay in `uploads/` and are git-ignored.
- The exception scrubber strips API keys and absolute paths from any
  error surfaced to the UI before the user sees it.
- CSRF double-submit cookie + single-flight semaphore on the analyse
  route prevent CSRF and accidental double-submission.

## Author

Safwan Ahmed. Day 04 of the 30-day finance + AI sprint, 2026.

## License

MIT. See `LICENSE`.
