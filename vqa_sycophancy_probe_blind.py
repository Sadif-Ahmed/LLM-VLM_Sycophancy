"""
VLM sycophancy probe, "blind" ablation — isolates the cost of losing visual
grounding from the cost of injecting fake counter-evidence.

Identical setup and pushback wording to vqa_sycophancy_probe_without_pres.py
(pushback_prompts.json's "vqa_no_pres" set — no prescription ever mentioned),
but unlike that script, the real question image is deliberately dropped after
turn 0 instead of being resent every turn. No second image ever replaces it.

This exists to disentangle vqa_sycophancy_probe.py's confounded "image"
condition, which loses the real image AND gains a fake one on the same turn:

  no_pres (image every turn, no prescription)  vs.  blind (image only turn 0,
  no prescription)   ->  isolates the pure cost of losing grounding, wording
  held constant.

  blind (no image from turn 1, no prescription)  vs.  image (no image from
  turn 1, prescription referenced every turn)   ->  isolates the marginal
  cost of the fake evidence, holding "no visual access" constant.

Reuses provider/call/retry plumbing from conversation_sim.py, the flip
detector + connection test + logging helpers from sycophancy_probe.py, the
no-prescription prompt set from vqa_sycophancy_probe_without_pres.py, and the
image-stripping helper from vqa_sycophancy_probe.py — none of those files are
touched by this one.
"""
import argparse
import base64
import io
import json
import logging
import random
import re
from pathlib import Path

from datasets import load_from_disk
from PIL import Image

from conversation_sim import PROVIDERS, call_llm, resolve_api_key
from sycophancy_probe import detect_flip, test_connection, append_results_log, select_pushback_turns, refused_turns, build_summary, load_completed, output_paths, write_results_json
from vqa_sycophancy_probe import strip_images_except_last
from vqa_sycophancy_probe_without_pres import NO_PRES_PROMPTS

SCRIPT_DIR = Path(__file__).parent

# NVIDIA NIM vision models cap input images at 1120x1120 (see nvidia_client.py).
MAX_IMAGE_DIM = 1120


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

    content, _, _ = call_llm(provider_cfg, api_key, model, strip_images_except_last(messages), temperature, max_tokens, timeout, rpm)
    answers = [extract_yesno(content)]
    turns.append({"turn": 0, "role": "assistant", "content": content, "answer": answers[0]})
    messages.append({"role": "assistant", "content": content})

    for i, template in enumerate(pushback_templates, start=1):
        pushback = template.format(wrong=wrong)
        messages.append({"role": "user", "content": pushback})
        turns.append({"turn": i, "role": "user", "content": pushback})

        content, _, _ = call_llm(provider_cfg, api_key, model, strip_images_except_last(messages), temperature, max_tokens, timeout, rpm)
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

    # The core of this ablation: the real image must disappear from the
    # payload the moment a text-only pushback turn becomes the latest
    # message, exactly like vqa_sycophancy_probe.py's confounded "image"
    # condition does from turn 2 on — but with no prescription ever
    # mentioned, holding the wording identical to vqa_no_pres.
    fake_history = [
        {"role": "user", "content": [{"type": "text", "text": "q1"}, {"type": "image_url", "image_url": {"url": "data:img0"}}]},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "plain pushback, no image"},
    ]
    stripped = strip_images_except_last(fake_history)
    assert stripped[0]["content"] == "q1"
    assert stripped[2]["content"] == "plain pushback, no image"

    assert "prescription" not in NO_PRES_PROMPTS["default"]["pushback_templates"][0].lower()

    print("selftest OK")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="VLM sycophancy flip probe over VQA-RAD (yes/no subset) — language-only pushback, "
                     "same wording as vqa_sycophancy_probe_without_pres.py, but the real image is dropped "
                     "after turn 0 instead of resent every turn"
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
    p.add_argument("--prompt-set", choices=list(NO_PRES_PROMPTS), default="default",
                    help="VQA yes/no system prompt + 'vqa_no_pres' pushback wording (same as vqa_sycophancy_probe_without_pres.py) — see system_prompts.json['vqa'] / pushback_prompts.json['vqa_no_pres']")
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

    leaf_dir, transcripts_dir = output_paths(args.model, "blind", args.prompt_set)
    try:
        prompt_set = select_pushback_turns(NO_PRES_PROMPTS[args.prompt_set], args.pushback_turns)
    except ValueError as e:
        raise SystemExit(f"[error] {e}")

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
        result = run_probe(idx, item, provider_cfg, api_key, model, args.temperature, args.max_tokens, args.timeout, rpm, prompt_set)
        flip = result["flipped_at_turn"]
        print(f"  correct={result['correct_answer']} initial={result['answers_by_turn'][0]} final={result['answers_by_turn'][-1]} flipped_at_turn={flip}")

        transcript_path = transcripts_dir / f"{idx}.json"
        transcript_path.write_text(json.dumps({
            **result, "model": args.model, "prompt_set": args.prompt_set, "evidence": "blind",
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
        "prompt_set": args.prompt_set, "evidence": "blind",
    }, summary, results)
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()
