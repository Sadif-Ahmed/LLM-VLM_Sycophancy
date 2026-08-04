"""
VLM sycophancy probe, prescription-free ablation of vqa_sycophancy_probe.py.

Same setup as vqa_sycophancy_probe.py — ask a vision model a VQA-RAD yes/no
question (image + question in one turn), then apply 3 escalating pushback
turns — but with NO fabricated "proof" image ever attached. Pushback wording
comes from pushback_prompts.json's "vqa_no_pres" set: the same radiologist
colleague -> two more radiologists -> board-certified attending escalation as
the image-evidence "vqa" set, with only the prescription-specific phrases
removed, paired with the same yes/no system prompt from system_prompts.json's
"vqa" set. This isolates whether the high flip rates seen with the fake
prescription image come from the image itself or from the escalating
language alone, without also changing the wording/persona style.

Reuses provider/call/retry plumbing from conversation_sim.py and the flip
detector + connection test from sycophancy_probe.py.
"""
import argparse
import base64
import io
import json
import logging
import random
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from datasets import load_from_disk
from PIL import Image

from conversation_sim import PROVIDERS, call_llm, resolve_api_key
from sycophancy_probe import detect_flip, test_connection, next_seq, append_results_log, select_pushback_turns, refused_turns, build_summary, load_completed

SCRIPT_DIR = Path(__file__).parent


def load_no_pres_prompt_set() -> dict:
    """Combine the VQA yes/no system prompts (system_prompts.json['vqa']) with the
    'vqa_no_pres' pushback wording (pushback_prompts.json['vqa_no_pres']) — the
    same radiologist/nurse/attending escalation as the image-evidence 'vqa' set,
    with only the prescription-specific phrases stripped out, so this is a clean
    ablation of just the fake image rather than a switch to different wording
    entirely (the generic MedMCQA 'text' set phrases things very differently).
    Using system_prompts.json['text'] would also be wrong here: that pairs with
    a letter-based "Answer: <letter>" instruction, which breaks extract_yesno()
    on a yes/no task."""
    vqa_system = json.loads((SCRIPT_DIR / "system_prompts.json").read_text(encoding="utf-8"))["vqa"]
    no_pres_pushback = json.loads((SCRIPT_DIR / "pushback_prompts.json").read_text(encoding="utf-8"))["vqa_no_pres"]
    return {name: {"system_prompt": sp, "pushback_templates": no_pres_pushback[name]} for name, sp in vqa_system.items()}


NO_PRES_PROMPTS = load_no_pres_prompt_set()

# NVIDIA NIM vision models cap input images at 1120x1120 (see nvidia_client.py).
MAX_IMAGE_DIM = 1120

# Only the turn-0 question image is ever sent — with no second image attached on
# any pushback turn, every call's message history naturally carries at most one
# image, so no history-stripping is needed here (unlike vqa_sycophancy_probe.py,
# which has to strip earlier images once a second, fake one is added).


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


def extract_yesno(text: str) -> str | None:
    m = re.search(r"\b(yes|no)\b", text, re.IGNORECASE)
    return m.group(1).capitalize() if m else None


def format_question(item: dict) -> tuple[str, str, str]:
    """Return (question, correct Yes/No, wrong Yes/No to push toward)."""
    correct = item["answer"].strip().capitalize()
    wrong = "No" if correct == "Yes" else "Yes"
    return item["question"], correct, wrong


def run_probe(item_id, item, provider_cfg, api_key, model, temperature, max_tokens, timeout, rpm, prompt_set: dict) -> dict:
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

    content, _, _ = call_llm(provider_cfg, api_key, model, messages, temperature, max_tokens, timeout, rpm)
    answers = [extract_yesno(content)]
    turns.append({"turn": 0, "role": "assistant", "content": content, "answer": answers[0]})
    messages.append({"role": "assistant", "content": content})

    for i, template in enumerate(pushback_templates, start=1):
        pushback = template.format(wrong=wrong)
        messages.append({"role": "user", "content": pushback})
        turns.append({"turn": i, "role": "user", "content": pushback})

        content, _, _ = call_llm(provider_cfg, api_key, model, messages, temperature, max_tokens, timeout, rpm)
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
    assert detect_flip(["Yes", "Yes", None, "Yes"], "Yes") is None   # refused mid-way, not a flip
    assert refused_turns(["Yes", None, "No", None]) == [1, 3]

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

    print("selftest OK")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="VLM sycophancy flip probe over VQA-RAD (yes/no subset) — language-only pushback, no fake image evidence"
    )
    p.add_argument("--provider", choices=list(PROVIDERS), default="nvidia")
    p.add_argument("--model", required=True, help="Vision-capable model name, or comma-separated fallback list")
    p.add_argument("--dataset-dir", default=str(SCRIPT_DIR / "data" / "vqa_rad"))
    p.add_argument("--split", choices=["train", "test"], default="train")
    p.add_argument("--n", type=int, default=5, help="Number of questions to sample")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--rpm", type=int, default=None)
    p.add_argument("--timeout", type=float, default=600.0, help="Read timeout in seconds")
    p.add_argument("--output", default=None, help="Output JSON path (default: results/<dataset>_no_pres/vqa_sycophancy_probe_without_pres_<uuid>.json)")
    p.add_argument("--transcripts-dir", default=str(SCRIPT_DIR / "transcripts"))
    p.add_argument("--prompt-set", choices=list(NO_PRES_PROMPTS), default="default",
                    help="VQA yes/no system prompt + 'vqa_no_pres' pushback wording (same escalation as 'vqa', prescription phrases removed) — see system_prompts.json['vqa'] / pushback_prompts.json['vqa_no_pres']")
    p.add_argument("--pushback-turns", type=int, default=10, help="Number of escalating pushback turns to run, 1-10 (default: 10, the full authored escalation)")
    p.add_argument("--selftest", action="store_true")
    return p


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

    print(f"Testing connection to {args.provider} ({args.model})...")
    try:
        model_used = test_connection(provider_cfg, api_key, model, args.timeout, rpm)
    except Exception as e:
        raise SystemExit(f"[error] connection test failed: {e}")
    print(f"Connection OK (model={model_used})")

    ds = load_from_disk(args.dataset_dir)[args.split]
    ds = ds.filter(lambda x: x["answer"].strip().lower() in ("yes", "no"))
    rng = random.Random(args.seed)
    indices = rng.sample(range(len(ds)), min(args.n, len(ds)))

    # "_no_pres" keeps this ablation's transcripts/results fully separate from
    # vqa_sycophancy_probe.py's image-evidence runs, even though both read the
    # same underlying --dataset-dir, so RESULTS.txt in each folder never mixes
    # the two conditions together.
    dataset_name = Path(args.dataset_dir).name + "_no_pres"
    model_tag = re.sub(r"[^A-Za-z0-9_.-]+", "_", args.model)
    transcripts_dir = Path(args.transcripts_dir) / dataset_name / model_tag / args.prompt_set
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    seq = next_seq(transcripts_dir)
    try:
        prompt_set = select_pushback_turns(NO_PRES_PROMPTS[args.prompt_set], args.pushback_turns)
    except ValueError as e:
        raise SystemExit(f"[error] {e}")

    completed = load_completed(transcripts_dir)
    done_ids = {r["item_id"] for r in completed}
    if completed:
        print(f"Resuming: {len(completed)} item(s) already done in {transcripts_dir}, skipping those.")

    results = []
    for idx in indices:
        if idx in done_ids:
            continue
        item = ds[idx]
        print(f"[{idx}] {item['question'][:80]}...")
        result = run_probe(idx, item, provider_cfg, api_key, model, args.temperature, args.max_tokens, args.timeout, rpm, prompt_set)
        flip = result["flipped_at_turn"]
        print(f"  correct={result['correct_answer']} initial={result['answers_by_turn'][0]} final={result['answers_by_turn'][-1]} flipped_at_turn={flip}")

        transcript_path = transcripts_dir / f"{seq:03d}.json"
        transcript_path.write_text(json.dumps({
            **result, "model": args.model, "prompt_set": args.prompt_set, "evidence": "none",
        }, indent=2), encoding="utf-8")
        seq += 1

        results.append(result)

    results = completed + results
    summary = build_summary(results)
    print(f"Summary: {summary}")

    append_results_log(transcripts_dir, args, summary, results)

    results_dir = SCRIPT_DIR / "results" / dataset_name / model_tag / args.prompt_set
    results_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else results_dir / f"{uuid.uuid4()}.json"
    output_path.write_text(json.dumps({
        "started_at": datetime.now(timezone.utc).isoformat(),
        "provider": args.provider, "model": args.model, "split": args.split, "seed": args.seed,
        "prompt_set": args.prompt_set, "evidence": "none",
        "summary": summary, "results": results,
    }, indent=2), encoding="utf-8")
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()
