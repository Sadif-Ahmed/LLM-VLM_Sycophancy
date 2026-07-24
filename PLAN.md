# Conversation Simulator — Design Plan v2 (NVIDIA NIM + OpenRouter)

## 1. Goal
Same as before: CLI tool, bounded conversation context, per-turn user
prompts, full JSON transcript on exit. This version replaces the generic
"bring your own endpoint" adapter with two concrete, named providers,
modeled on the patterns already in your `nvidia_client.py`.

## 2. What Changes From the Previous (Generic Endpoint) Plan
- Back to using the `openai` Python client library (not raw `requests`) —
  both NVIDIA NIM and OpenRouter are OpenAI-compatible, and your existing
  code already depends on `openai`, `httpx`, and `tenacity`. No reason to
  avoid them now that the real targets are known.
- `--endpoint-url` / `--auth-header` generic flags are replaced by a
  `--provider {nvidia,openrouter}` switch, each with its own base URL,
  API-key env var, and default rate limit — mirroring how `NVIDIA_BASE_URL`
  is hardcoded as a constant in your file.
- Rate limiting and retry logic are pulled directly from your file's
  pattern rather than reinvented.

## 3. Provider Configs

| | NVIDIA NIM | OpenRouter |
|---|---|---|
| Base URL | `https://integrate.api.nvidia.com/v1` | `https://openrouter.ai/api/v1` |
| API key env var | `NVIDIA_API_KEY` | `OPENROUTER_API_KEY` |
| Default rate limit | 40 RPM (from your file) | Configurable, free tier is tighter — default conservatively, override with `--rpm` |
| Client | `openai.OpenAI(base_url=..., api_key=...)` | same |

Both go through the same call path — the only per-provider difference is
which config block gets loaded.

## 4. Reused From `nvidia_client.py`

- **Rate limiting**: same `_enforce_rate_limit(rpm)` pattern — a module-level
  lock + last-call timestamp, sleeping to maintain minimum spacing between
  calls. Generalized to take `rpm` per active provider instead of a
  hardcoded 40.
- **Retry**: same `tenacity` decorator shape — exponential backoff,
  `stop_after_attempt(3)`, `reraise=True` — wrapping the actual API call.
- **Model fallback**: same pattern as `call_nvidia_structured`'s
  `models_to_try` loop — `--model` accepts either a single model name or a
  comma-separated list; on failure (after retries exhaust) it moves to the
  next model in the list before giving up.
- **Timeout handling**: same `httpx.Timeout(read=..., connect=...)` passed
  into the client, exposed as a flag with a sane default rather than
  hardcoded.
- **Truncation guard**: same `finish_reason == "length"` check — treated as
  an error (not a silent partial reply) since a cut-off turn would corrupt
  the transcript.

## 5. Deliberately NOT Carried Over (for now)
Your file also handles PDF-to-image conversion, image resizing, and
structured JSON-schema output (`response_format` / `json_schema`). None of
that is wired into the base conversation loop, since this tool is plain
multi-turn *text* chat, not document evaluation. The call function keeps an
unused `schema=None` parameter so this can be turned on later without
restructuring anything, but it's off by default.

## 6. Core Components (unchanged from v1)

### Two conversation stores
- **Windowed history** — what's sent to the model each call.
- **Full log** — every turn ever recorded, untouched by windowing.

### Turn loop
1. Prompt user for input.
2. Check exit command (`/exit`, `/quit`, `/end`, `/stop`) or `--max-turns`
   cap.
3. Assemble messages: `[system?] + windowed_history + [new user message]`.
4. Rate-limit, then call the active provider (with retry + model fallback),
   measure latency, capture token usage.
5. Print reply, append to both stores.
6. Loop.

### Exporter
On exit, serialize the full log plus session + provider metadata to one
JSON file.

## 7. Context Window Strategy (unchanged)
Last `N` user/assistant *pairs* (`--max-context-turns`, default 6; `0` =
unlimited) sent per call. Full log always keeps everything.

## 8. Config Surface
`--provider {nvidia,openrouter}`, `--model` (single or comma-separated
fallback list), `--system-prompt`, `--max-context-turns`, `--max-turns`,
`--rpm` (override default per-provider rate limit), `--timeout`,
`--output`, `--dry-run`.

API keys come from `NVIDIA_API_KEY` / `OPENROUTER_API_KEY` env vars,
matching how your existing client expects `api_key` to be passed in rather
than hardcoded.

## 9. Output Schema (unchanged, provider field now concrete)
```jsonc
{
  "session_id": "...",
  "started_at": "...", "ended_at": "...",
  "provider": {"name": "nvidia", "base_url": "...", "model": "...", "rpm": 40},
  "config": {"system_prompt": null, "max_context_turns": 6, "max_turns": 0},
  "total_turns": 4,
  "conversation": [
    {"turn": 1, "role": "user", "content": "...", "timestamp": "..."},
    {"turn": 1, "role": "assistant", "content": "...", "timestamp": "...",
     "latency_ms": 412, "usage": {...}, "model_used": "...",
     "context_messages_sent_this_call": 1}
  ]
}
```
`model_used` is new — meaningful once model fallback is in play, so the
transcript records which model in the list actually answered each turn.

## 10. Error Handling (unchanged in spirit)
A failed call (after retries + model fallback exhaust) logs a
`"role": "error"` entry and lets the session continue rather than crashing.

## 11. Extension Points (unchanged)
- Scripted pushback queue instead of manual `input()`.
- Post-hoc judge pass over the saved JSON for flip-style metrics.
- Turn on `schema`/structured-output support later if a turn needs
  parseable JSON instead of free text.
