r"""

Example command: .\.venv\Scripts\python.exe vqa_sycophancy_probe_hf.py --provider huggingface --model Qwen/Qwen3.5-9B --evidence none --n 5 --max-tokens 4096


VLM sycophancy probe, Hugging Face Inference Providers edition.

Unifies what vqa_sycophancy_probe.py and vqa_sycophancy_probe_without_pres.py
each do separately, behind one --evidence flag, and adds "huggingface" as a
third --provider option — without modifying any of those existing files.

--evidence image  (default): same as vqa_sycophancy_probe.py — a fake proof
    image (the fabricated prescription) is attached alongside the first
    pushback turn. Pushback wording comes from pushback_prompts.json["vqa"].
    Requires --proof-yes-image/--proof-no-image.
--evidence none: same as vqa_sycophancy_probe_without_pres.py — no second
    image is ever attached, pure language pressure. Pushback wording comes
    from pushback_prompts.json["vqa_no_pres"] (same escalation/persona as
    "vqa", prescription phrases removed).

Both modes share the same yes/no system prompt (system_prompts.json["vqa"])
and the same --prompt-set personas (default / neighbor_nurse_doctor / generic).

--provider {nvidia,openrouter,huggingface}: "huggingface" is added to a LOCAL
copy of conversation_sim.py's PROVIDERS dict, merged at import time here —
conversation_sim.py itself is not touched. Hugging Face's Inference Providers
router (https://router.huggingface.co/v1) is OpenAI-compatible, so it works
through the exact same call_llm() plumbing as NVIDIA NIM and OpenRouter.
Needs a fine-grained HF token with the "Make calls to Inference Providers"
permission, from either the HF_TOKEN env var or a local hf_token.txt file
(same fallback pattern as NVIDIA's api_key.txt, kept in its own file/function
here rather than editing conversation_sim.py's resolve_api_key).

Output lands under the same results/<model>/<variant>/<prompt>/ layout every
probe script uses (see sycophancy_probe.output_paths) — variant is "image"
or "no_pres" depending on --evidence. No source/runner disambiguation:
running the same model through this script and, say, vqa_sycophancy_probe.py
lands in the identical folder, so stick to one backend per model. Checkpoints
and resumes the same way every other probe script does: item_id-keyed
transcripts in transcripts/, load_completed() skips whatever's already there
on rerun.

Reuses provider/call/retry plumbing from conversation_sim.py and the flip
detector + connection test + logging helpers from sycophancy_probe.py.
"""
import argparse
import base64
import io
import json
import logging
import os
import random
import re
from pathlib import Path

from datasets import load_from_disk
from PIL import Image

from conversation_sim import PROVIDERS as BASE_PROVIDERS, call_llm, resolve_api_key
from sycophancy_probe import detect_flip, load_completed, append_results_log, refused_turns, build_summary, output_paths, write_results_json

SCRIPT_DIR = Path(__file__).parent


def test_connection(provider_cfg, api_key, model, timeout, rpm, max_tokens: int) -> str:
    """Same round-trip check as sycophancy_probe.test_connection, but using
    --max-tokens instead of a hardcoded 64 — some HF-routed reasoning models
    burn far more than 64 tokens on hidden reasoning before emitting any
    visible content, even for a trivial prompt, so that fixed constant always
    truncates on those models. Defined locally rather than editing that
    shared function."""
    _, _, model_used = call_llm(
        provider_cfg, api_key, model,
        [{"role": "user", "content": "Reply with exactly: ok"}],
        0.0, max_tokens, timeout, rpm,
    )
    return model_used


def resolve_hf_token() -> str:
    """HF_TOKEN env var, falling back to a local hf_token.txt file — the same
    pattern conversation_sim.py uses for NVIDIA's api_key.txt, kept as a
    separate file/function here so it doesn't collide with that file or
    require editing conversation_sim.py's resolve_api_key (which only
    file-falls-back for "nvidia" specifically)."""
    key = os.environ.get("HF_TOKEN")
    if key:
        return key.strip()
    token_file = SCRIPT_DIR / "hf_token.txt"
    if token_file.exists():
        return token_file.read_text(encoding="utf-8").strip()
    raise RuntimeError("No HF token found — set HF_TOKEN or create hf_token.txt in this directory")

# "huggingface" added locally here only — conversation_sim.py's own PROVIDERS
# dict is untouched. call_llm()/resolve_api_key() only need base_url/env_var/
# default_rpm, so this merged dict works with them exactly like the built-in
# providers do.
PROVIDERS = {
    **BASE_PROVIDERS,
    "huggingface": {
        "base_url": "https://router.huggingface.co/v1",
        "env_var": "HF_TOKEN",
        "default_rpm": 20,  # conservative guess — HF's actual per-provider limits vary; override with --rpm
    },
}

# NVIDIA NIM vision models cap input images at 1120x1120 (see nvidia_client.py).
# Applied to every image sent regardless of provider — a safe, conservative cap.
MAX_IMAGE_DIM = 1120

VQA_PERSONAS = list(json.loads((SCRIPT_DIR / "prompts" / "system_prompts.json").read_text(encoding="utf-8"))["vqa"])


def load_prompt_sets(evidence: str) -> dict:
    """VQA yes/no system prompts (system_prompts.json['vqa']) paired with either
    the image-evidence pushback wording ('vqa') or the prescription-free wording
    ('vqa_no_pres'), matching vqa_sycophancy_probe.py / vqa_sycophancy_probe_without_pres.py
    respectively. Depends on --evidence, so this is called at runtime in main()
    rather than built as a module-level constant."""
    vqa_system = json.loads((SCRIPT_DIR / "prompts" / "system_prompts.json").read_text(encoding="utf-8"))["vqa"]
    domain = "vqa" if evidence == "image" else "vqa_no_pres"
    pushback = json.loads((SCRIPT_DIR / "prompts" / "pushback_prompts.json").read_text(encoding="utf-8"))[domain]
    return {name: {"system_prompt": sp, "pushback_templates": pushback[name]} for name, sp in vqa_system.items()}


def pil_to_base64(img: Image.Image, max_dim: int = MAX_IMAGE_DIM, quality: int = 85) -> str:
    """Encode a PIL image to base64 JPEG, downscaling if either edge exceeds max_dim."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def load_image_b64(path: str, max_dim: int = MAX_IMAGE_DIM) -> str:
    return pil_to_base64(Image.open(path), max_dim)


def strip_images_except_last(messages: list[dict]) -> list[dict]:
    """Downgrade every message except the newest to text-only. Only relevant to
    --evidence image, which can have TWO image-bearing turns (the real question
    image, and the fake proof image on pushback turn 1) — most inference
    backends (NIM included) accept at most one image per call. Not used at all
    for --evidence none, where only turn 0 ever carries an image, so it never
    needs stripping (see build_call_messages)."""
    last_idx = len(messages) - 1
    out = []
    for i, m in enumerate(messages):
        content = m["content"]
        if i != last_idx and isinstance(content, list):
            text = next((p["text"] for p in content if p.get("type") == "text"), "")
            out.append({"role": m["role"], "content": text})
        else:
            out.append(m)
    return out


def build_call_messages(messages: list[dict], evidence: str) -> list[dict]:
    """--evidence image: strip down to <=1 image per call, as above.
    --evidence none: pass through untouched — the turn-0 image is the only one
    ever present, so every call already has <=1 image without stripping, and
    stripping unconditionally here would wrongly erase it from turns 1-3."""
    return strip_images_except_last(messages) if evidence == "image" else messages


def extract_yesno(text: str) -> str | None:
    m = re.search(r"\b(yes|no)\b", text, re.IGNORECASE)
    return m.group(1).capitalize() if m else None


def format_question(item: dict) -> tuple[str, str, str]:
    """Return (question, correct Yes/No, wrong Yes/No to push toward)."""
    correct = item["answer"].strip().capitalize()
    wrong = "No" if correct == "Yes" else "Yes"
    return item["question"], correct, wrong


def run_probe(item_id, item, provider_cfg, api_key, model, temperature, max_tokens, timeout, rpm,
              prompt_set: dict, evidence: str, proof_b64: dict | None) -> dict:
    system_prompt = prompt_set["system_prompt"]
    pushback_templates = prompt_set["pushback_templates"]

    question, correct, wrong = format_question(item)
    img_b64 = pil_to_base64(item["image"])

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
        ]},
    ]
    turns = [{"turn": 0, "role": "user", "content": question}]

    content, _, _ = call_llm(provider_cfg, api_key, model, build_call_messages(messages, evidence), temperature, max_tokens, timeout, rpm)
    answers = [extract_yesno(content)]
    turns.append({"turn": 0, "role": "assistant", "content": content, "answer": answers[0]})
    messages.append({"role": "assistant", "content": content})

    for i, template in enumerate(pushback_templates, start=1):
        pushback = template.format(wrong=wrong)
        if evidence == "image" and i == 1:
            messages.append({"role": "user", "content": [
                {"type": "text", "text": pushback},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{proof_b64[wrong]}"}},
            ]})
        else:
            messages.append({"role": "user", "content": pushback})
        turns.append({"turn": i, "role": "user", "content": pushback})

        content, _, _ = call_llm(provider_cfg, api_key, model, build_call_messages(messages, evidence), temperature, max_tokens, timeout, rpm)
        answers.append(extract_yesno(content))
        turns.append({"turn": i, "role": "assistant", "content": content, "answer": answers[-1]})
        messages.append({"role": "assistant", "content": content})

        if detect_flip(answers, correct) is not None:
            break  # flipped off the correct answer — no need to keep pushing

    flip_turn = detect_flip(answers, correct)
    return {
        "item_id": item_id,
        "question": question,
        "correct_answer": correct,
        "pushed_toward": wrong,
        "answers_by_turn": answers,
        "initial_correct": answers[0] == correct,
        "final_correct": answers[-1] == correct,
        "flipped_at_turn": flip_turn,
        "refused_turns": refused_turns(answers),
        "stopped_early": flip_turn is not None and len(answers) < len(pushback_templates) + 1,
        "turns": turns,
        "messages": messages,
    }


def _selftest() -> None:
    assert extract_yesno("Answer: Yes. Because effusion is visible.") == "Yes"
    assert extract_yesno("I'd say no.") == "No"
    assert extract_yesno("I am not sure about this case.") is None

    assert detect_flip(["Yes", "Yes", "Yes", "Yes"], "Yes") is None  # held firm
    assert detect_flip(["Yes", "Yes", "No", "No"], "Yes") == 2       # flipped on 2nd pushback
    assert detect_flip(["No", "No", "Yes", "Yes"], "Yes") is None    # started wrong, not a "flip"
    assert detect_flip(["Yes", "No", "Yes", "No"], "Yes") == 1       # flipped, even if it wavers back

    question, correct, wrong = format_question({"question": "Is there an effusion?", "answer": "yes"})
    assert (question, correct, wrong) == ("Is there an effusion?", "Yes", "No")
    _, correct2, wrong2 = format_question({"question": "Q?", "answer": "No"})
    assert (correct2, wrong2) == ("No", "Yes")

    big = Image.new("RGB", (2000, 1000), color=(255, 0, 0))
    decoded_big = Image.open(io.BytesIO(base64.b64decode(pil_to_base64(big, max_dim=1120))))
    assert max(decoded_big.size) <= 1120

    small = Image.new("RGB", (100, 100), color=(0, 255, 0))
    decoded_small = Image.open(io.BytesIO(base64.b64decode(pil_to_base64(small, max_dim=1120))))
    assert decoded_small.size == (100, 100)

    fake_history = [
        {"role": "user", "content": [{"type": "text", "text": "q1"}, {"type": "image_url", "image_url": {"url": "data:img0"}}]},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": [{"type": "text", "text": "q2"}, {"type": "image_url", "image_url": {"url": "data:img1"}}]},
    ]
    stripped = strip_images_except_last(fake_history)
    assert stripped[0]["content"] == "q1"
    assert stripped[1]["content"] == "a1"
    assert isinstance(stripped[2]["content"], list)

    assert build_call_messages(fake_history, "image") == strip_images_except_last(fake_history)
    assert build_call_messages(fake_history, "none") == fake_history

    text_prompts = load_prompt_sets("none")
    image_prompts = load_prompt_sets("image")
    assert "prescription" not in text_prompts["default"]["pushback_templates"][0].lower()
    assert "prescription" in image_prompts["default"]["pushback_templates"][0].lower()
    assert text_prompts["default"]["system_prompt"] == image_prompts["default"]["system_prompt"]

    assert "huggingface" in PROVIDERS
    assert PROVIDERS["nvidia"] == BASE_PROVIDERS["nvidia"]  # confirms conversation_sim.PROVIDERS untouched

    print("selftest OK")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="VLM sycophancy flip probe over VQA-RAD — supports NVIDIA NIM, OpenRouter, and Hugging Face "
                     "Inference Providers, with/without fake prescription-image evidence"
    )
    p.add_argument("--provider", choices=list(PROVIDERS), default="nvidia")
    p.add_argument("--model", required=True,
                   help="Vision-capable model name, or comma-separated fallback list. "
                        "For --provider huggingface, use the HF Hub repo id, optionally 'org/model:provider'")
    p.add_argument("--evidence", choices=["image", "none"], default="image",
                   help="'image': attach the fake prescription on pushback turn 1 (needs --proof-*-image). "
                        "'none': pure language pushback, no second image ever attached")
    p.add_argument("--dataset-dir", default=str(SCRIPT_DIR / "data" / "vqa_rad"))
    p.add_argument("--split", choices=["train", "test"], default="train")
    p.add_argument("--n", type=int, default=5, help="Number of questions to sample")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--rpm", type=int, default=None)
    p.add_argument("--timeout", type=float, default=600.0, help="Read timeout in seconds")
    p.add_argument("--prompt-set", choices=VQA_PERSONAS, default="default",
                    help="Persona for both system prompt and pushback wording — see system_prompts.json['vqa'] / "
                         "pushback_prompts.json['vqa' or 'vqa_no_pres']")
    p.add_argument("--proof-yes-image", default=None, help="Path to fake 'confirmed Yes case' proof image (required with --evidence image, unless --selftest)")
    p.add_argument("--proof-no-image", default=None, help="Path to fake 'confirmed No case' proof image (required with --evidence image, unless --selftest)")
    p.add_argument("--selftest", action="store_true")
    return p


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_arg_parser().parse_args()
    if args.selftest:
        _selftest()
        return

    if args.evidence == "image" and (not args.proof_yes_image or not args.proof_no_image):
        raise SystemExit("--proof-yes-image and --proof-no-image are required with --evidence image (unless --selftest)")

    provider_cfg = PROVIDERS[args.provider]
    api_key = resolve_hf_token() if args.provider == "huggingface" else resolve_api_key(args.provider, provider_cfg["env_var"])
    model = args.model.split(",") if "," in args.model else args.model
    rpm = args.rpm or provider_cfg["default_rpm"]

    print(f"Testing connection to {args.provider} ({args.model})...")
    try:
        model_used = test_connection(provider_cfg, api_key, model, args.timeout, rpm, args.max_tokens)
    except Exception as e:
        raise SystemExit(f"[error] connection test failed: {e}")
    print(f"Connection OK (model={model_used})")

    proof_b64 = None
    if args.evidence == "image":
        proof_b64 = {
            "Yes": load_image_b64(args.proof_yes_image),
            "No": load_image_b64(args.proof_no_image),
        }

    ds = load_from_disk(args.dataset_dir)[args.split]
    ds = ds.filter(lambda x: x["answer"].strip().lower() in ("yes", "no"))
    rng = random.Random(args.seed)
    indices = rng.sample(range(len(ds)), min(args.n, len(ds)))

    variant = "image" if args.evidence == "image" else "no_pres"
    leaf_dir, transcripts_dir = output_paths(args.model, variant, args.prompt_set)
    prompt_set = load_prompt_sets(args.evidence)[args.prompt_set]

    completed = load_completed(transcripts_dir)
    done_ids = {r["item_id"] for r in completed}
    if completed:
        print(f"Resuming: {len(completed)} item(s) already done in {transcripts_dir}, skipping those.")

    results = []
    for i, idx in enumerate(indices, start=1):
        if idx in done_ids:
            continue
        item = ds[idx]
        print(f"[{i}/{len(indices)}] [{idx}] {item['question'][:80]}...")
        try:
            result = run_probe(idx, item, provider_cfg, api_key, model, args.temperature, args.max_tokens, args.timeout, rpm,
                                prompt_set, args.evidence, proof_b64)
        except Exception as e:
            # One bad question (truncation, transient API error, etc.) shouldn't
            # discard every already-completed question in this batch — log it
            # and move on; RESULTS.txt/summary still reflect whatever succeeded.
            logging.error(f"[{idx}] failed, skipping: {e}")
            continue
        flip = result["flipped_at_turn"]
        print(f"  correct={result['correct_answer']} initial={result['answers_by_turn'][0]} final={result['answers_by_turn'][-1]} flipped_at_turn={flip}")

        transcript_path = transcripts_dir / f"{idx}.json"
        transcript_path.write_text(json.dumps({
            **result, "model": args.model, "provider": args.provider,
            "prompt_set": args.prompt_set, "evidence": args.evidence,
        }, indent=2), encoding="utf-8")

        results.append(result)

    new_count = len(results)
    results = completed + results
    summary = build_summary(results)
    print(f"Summary: {summary}")

    if not new_count:
        print(f"Nothing new or repaired in {transcripts_dir} — all {len(results)} item(s) already checkpointed, skipping RESULTS.txt/results.json rewrite.")
        return

    append_results_log(leaf_dir, args, summary, results)
    output_path = write_results_json(leaf_dir, {
        "provider": args.provider, "model": args.model, "split": args.split, "seed": args.seed,
        "prompt_set": args.prompt_set, "evidence": args.evidence,
        "proof_yes_image": args.proof_yes_image, "proof_no_image": args.proof_no_image,
    }, summary, results)
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()
