"""
Conversation Simulator — CLI multi-turn chat against NVIDIA NIM or OpenRouter.
See PLAN.md for design. Rate-limit/retry/fallback patterns mirror nvidia_client.py.
"""
import argparse
import base64
import json
import logging
import mimetypes
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent
EXIT_COMMANDS = {"/exit", "/quit", "/end", "/stop"}
DEFAULT_TEMPERATURE = 1
DEFAULT_MAX_TOKENS = 2048

PROVIDERS = {
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "env_var": "NVIDIA_API_KEY",
        "default_rpm": 40,
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "env_var": "OPENROUTER_API_KEY",
        "default_rpm": 20,
    },
}

# ---- rate limiting (pattern from nvidia_client.py, generalized to any rpm) ----
_last_request_time = 0.0
_rate_limit_lock = threading.Lock()


def _enforce_rate_limit(rpm: int) -> None:
    global _last_request_time
    min_interval = 60.0 / rpm
    with _rate_limit_lock:
        now = time.time()
        elapsed = now - _last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _last_request_time = time.time()


@retry(
    wait=wait_exponential(multiplier=2, min=5, max=90),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _do_call(
    client: OpenAI,
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    rpm: int,
    schema: dict[str, Any] | None = None,  # unused for now; see PLAN.md #5
) -> tuple[str, dict | None]:
    _enforce_rate_limit(rpm)
    response = client.chat.completions.create(
        model=model, messages=messages, temperature=temperature, max_tokens=max_tokens
    )
    choice = response.choices[0]
    content = choice.message.content
    if choice.finish_reason == "length":
        raise ValueError(
            f"Response truncated at max_tokens={max_tokens} (finish_reason=length) — "
            "reasoning models can burn the whole budget on hidden reasoning tokens "
            "before emitting content; raise max_tokens"
        )
    if content is None:
        raise ValueError("Model returned empty content (None) — refusal or transient error")
    usage = response.usage.model_dump() if response.usage else None
    return content, usage


def call_llm(
    provider_cfg: dict,
    api_key: str,
    model: str | list[str],
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    timeout: float,
    rpm: int,
) -> tuple[str, dict | None, str]:
    """Call the active provider, trying each model in `model` (fallback list) in order."""
    models_to_try = [model] if isinstance(model, str) else model
    client = OpenAI(
        base_url=provider_cfg["base_url"],
        api_key=api_key,
        max_retries=0,  # tenacity handles retries above
        timeout=httpx.Timeout(timeout, connect=10.0),
    )
    last_err = None
    for m in models_to_try:
        try:
            content, usage = _do_call(client, m, messages, temperature, max_tokens, rpm)
            return content, usage, m
        except Exception as e:
            logger.warning(f"Model {m} failed after retries: {e}")
            last_err = e
            continue
    raise RuntimeError(f"All models failed. Last error: {last_err}")


def resolve_api_key(provider_name: str, env_var: str) -> str:
    key = os.environ.get(env_var)
    if key:
        return key.strip()
    if provider_name == "nvidia":
        key_file = SCRIPT_DIR / "api_key.txt"
        if key_file.exists():
            return key_file.read_text().strip()
    raise RuntimeError(f"No API key found — set {env_var} or provide api_key.txt (nvidia only)")


def context_window(full_log: list[dict], max_context_turns: int) -> list[dict]:
    """Last N user/assistant pairs as {role, content} messages. 0 = unlimited."""
    turns = [{"role": m["role"], "content": m["content"]} for m in full_log if m["role"] in ("user", "assistant")]
    if max_context_turns <= 0:
        return turns
    return turns[-(max_context_turns * 2):]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode_image(path: Path) -> str:
    """Read image file, return data: URI for vision-capable chat models."""
    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


class Session:
    def __init__(self, provider_name, provider_cfg, api_key, model, system_prompt, max_context_turns, rpm, timeout):
        self.session_id = str(uuid.uuid4())
        self.started_at = _now()
        self.provider_name = provider_name
        self.provider_cfg = provider_cfg
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.max_context_turns = max_context_turns
        self.rpm = rpm
        self.timeout = timeout
        self.full_log: list[dict] = []
        self.turn = 0

    def run(self, max_turns: int, dry_run: bool) -> None:
        while True:
            if max_turns and self.turn >= max_turns:
                break
            try:
                user_input = input("You: ").strip()
            except EOFError:
                break
            if user_input.lower() in EXIT_COMMANDS:
                break
            if not user_input:
                continue

            image_path_raw = input("Image path (blank=none): ").strip()
            content: Any = user_input
            if image_path_raw:
                image_path = Path(image_path_raw)
                if image_path.is_file():
                    content = [
                        {"type": "text", "text": user_input},
                        {"type": "image_url", "image_url": {"url": encode_image(image_path)}},
                    ]
                else:
                    print(f"[warn] image not found, sending text only: {image_path}")

            self.turn += 1
            self.full_log.append({"turn": self.turn, "role": "user", "content": content, "timestamp": _now()})

            messages = self._build_messages()
            if dry_run:
                print(f"[dry-run] would send {len(messages)} messages to {self.model}")
                continue

            start = time.time()
            try:
                content, usage, model_used = call_llm(
                    self.provider_cfg, self.api_key, self.model, messages,
                    DEFAULT_TEMPERATURE, DEFAULT_MAX_TOKENS, self.timeout, self.rpm,
                )
                latency_ms = int((time.time() - start) * 1000)
                self.full_log.append({
                    "turn": self.turn, "role": "assistant", "content": content, "timestamp": _now(),
                    "latency_ms": latency_ms, "usage": usage, "model_used": model_used,
                    "context_messages_sent_this_call": len(messages),
                })
                print(f"Assistant: {content}")
            except Exception as e:
                logger.error(f"Turn {self.turn} failed: {e}")
                self.full_log.append({"turn": self.turn, "role": "error", "content": str(e), "timestamp": _now()})
                print(f"[error] {e}")

    def _build_messages(self) -> list[dict]:
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(context_window(self.full_log, self.max_context_turns))
        return messages

    def export(self, output_path: Path) -> None:
        data = {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "ended_at": _now(),
            "provider": {
                "name": self.provider_name, "base_url": self.provider_cfg["base_url"],
                "model": self.model, "rpm": self.rpm,
            },
            "config": {
                "system_prompt": self.system_prompt, "max_context_turns": self.max_context_turns,
                "max_turns": self.turn,
            },
            "total_turns": self.turn,
            "conversation": self.full_log,
        }
        output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"Saved transcript to {output_path}")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Multi-turn conversation simulator (NVIDIA NIM / OpenRouter)")
    p.add_argument("--provider", choices=list(PROVIDERS), default="nvidia")
    p.add_argument("--model", required=True, help="Model name, or comma-separated fallback list")
    p.add_argument("--system-prompt", default=None)
    p.add_argument("--max-context-turns", type=int, default=6, help="0 = unlimited")
    p.add_argument("--max-turns", type=int, default=0, help="0 = unlimited")
    p.add_argument("--rpm", type=int, default=None, help="Override provider default rate limit")
    p.add_argument("--timeout", type=float, default=600.0, help="Read timeout in seconds")
    p.add_argument("--output", default=None, help="Output JSON path (default: session_<id>.json)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--selftest", action="store_true", help="Run self-check on pure logic and exit")
    return p


def _selftest() -> None:
    log = [
        {"turn": 1, "role": "user", "content": "hi"},
        {"turn": 1, "role": "assistant", "content": "hello"},
        {"turn": 2, "role": "user", "content": "how are you"},
        {"turn": 2, "role": "error", "content": "boom"},
        {"turn": 3, "role": "user", "content": "still there?"},
        {"turn": 3, "role": "assistant", "content": "yes"},
    ]
    assert context_window(log, 0) == [
        {"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "how are you"}, {"role": "user", "content": "still there?"},
        {"role": "assistant", "content": "yes"},
    ]
    assert context_window(log, 1) == [{"role": "user", "content": "still there?"}, {"role": "assistant", "content": "yes"}]
    assert context_window([], 6) == []
    print("selftest OK")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_arg_parser().parse_args()

    if args.selftest:
        _selftest()
        return

    provider_cfg = PROVIDERS[args.provider]
    api_key = resolve_api_key(args.provider, provider_cfg["env_var"])
    model = args.model.split(",") if "," in args.model else args.model
    rpm = args.rpm or provider_cfg["default_rpm"]

    session = Session(
        provider_name=args.provider, provider_cfg=provider_cfg, api_key=api_key, model=model,
        system_prompt=args.system_prompt, max_context_turns=args.max_context_turns,
        rpm=rpm, timeout=args.timeout,
    )
    output_path = Path(args.output) if args.output else SCRIPT_DIR / f"session_{session.session_id}.json"

    try:
        session.run(max_turns=args.max_turns, dry_run=args.dry_run)
    finally:
        if not args.dry_run:
            session.export(output_path)


if __name__ == "__main__":
    main()
