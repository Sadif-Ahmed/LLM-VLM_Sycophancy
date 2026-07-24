# Conversation Simulator

CLI tool for running bounded multi-turn conversations against NVIDIA NIM or
OpenRouter (both OpenAI-compatible), with a full JSON transcript saved on exit.

See [PLAN.md](PLAN.md) for design details.

## Setup

Requires Python 3.10+ and:

```
pip install openai httpx tenacity
```

### API key

NVIDIA:
- Set `NVIDIA_API_KEY` env var, **or**
- Drop the key in `api_key.txt` in this directory (already provided) — used
  automatically if the env var isn't set.

OpenRouter:
- Set `OPENROUTER_API_KEY` env var (no file fallback).

## Running

```
python conversation_sim.py --model meta/llama-3.1-8b-instruct
```

Type messages at the `You:` prompt. End the session with `/exit`, `/quit`,
`/end`, or `/stop` (or Ctrl+D). On exit, the transcript is written to
`session_<uuid>.json` in this directory.

### Flags

| Flag | Default | Notes |
|---|---|---|
| `--provider {nvidia,openrouter}` | `nvidia` | |
| `--model` | *required* | single model, or `a,b,c` for fallback order |
| `--system-prompt` | none | |
| `--max-context-turns` | `6` | last N user/assistant pairs sent per call; `0` = unlimited |
| `--max-turns` | `0` | cap on turns; `0` = unlimited |
| `--rpm` | provider default (nvidia `40`, openrouter `20`) | overrides rate limit |
| `--timeout` | `600.0` | read timeout, seconds |
| `--output` | `session_<uuid>.json` | transcript output path |
| `--dry-run` | off | prints what would be sent, makes no API calls |
| `--selftest` | off | runs the pure-logic self-check and exits (no key needed) |

### Examples

Model fallback list:

```
python conversation_sim.py --model meta/llama-3.1-8b-instruct,mistralai/mixtral-8x7b-instruct-v0.1
```

OpenRouter, capped at 10 turns, no context trimming:

```
python conversation_sim.py --provider openrouter --model openai/gpt-4o-mini --max-turns 10 --max-context-turns 0
```

Dry run (no network calls, just check message assembly):

```
python conversation_sim.py --model meta/llama-3.1-8b-instruct --dry-run
```

## Output

One JSON file per session: full turn-by-turn log (including any errors),
plus provider/config metadata. Schema documented in
[PLAN.md](PLAN.md#9-output-schema-unchanged-provider-field-now-concrete).

A failed turn (retries + model fallback exhausted) is logged as
`"role": "error"` and the session continues rather than crashing.
