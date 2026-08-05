"""
VLM sycophancy probe — ask a vision model a VQA-RAD yes/no question (image +
question in one turn), then apply escalating "radiologist reviewed the same
image and disagrees" pushback — including a fake proof image on the first
pushback turn — and check whether the model abandons a correct,
image-grounded answer under social pressure (clinical sycophancy, per
LLM_Sycophancy_Medical_Domain_Report.md section 4.3).
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
from sycophancy_probe import detect_flip, test_connection, append_results_log, load_prompt_set, select_pushback_turns, refused_turns, build_summary, load_completed

SCRIPT_DIR = Path(__file__).parent
VQA_PROMPTS = load_prompt_set("vqa")

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


def load_image_b64(path: str, max_dim: int = MAX_IMAGE_DIM) -> str:
    return pil_to_base64(Image.open(path), max_dim)


def strip_images_except_last(messages: list[dict]) -> list[dict]:
    """Downgrade every message except the newest to text-only.

    NVIDIA NIM accepts at most ONE base64 image per call (see
    nvidia_client.py). This probe has two image-bearing turns (the real
    question image, and the fake proof image on pushback turn 1); replaying
    the full message history naively would send both at once. Since only
    the newest message may carry an image, every call payload built this
    way ends up with <=1 image automatically.
    """
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


def extract_yesno(text: str) -> str | None:
    m = re.search(r"\b(yes|no)\b", text, re.IGNORECASE)
    return m.group(1).capitalize() if m else None


def format_question(item: dict) -> tuple[str, str, str]:
    """Return (question, correct Yes/No, wrong Yes/No to push toward)."""
    correct = item["answer"].strip().capitalize()
    wrong = "No" if correct == "Yes" else "Yes"
    return item["question"], correct, wrong


def run_probe(item_id, item, provider_cfg, api_key, model, temperature, max_tokens, timeout, rpm, proof_b64: dict, prompt_set: dict) -> dict:
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
        if i == 1:
            messages.append({"role": "user", "content": [
                {"type": "text", "text": pushback},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{proof_b64[wrong]}"}},
            ]})
        else:
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
    assert any(p.get("type") == "image_url" for p in stripped[2]["content"])

    print("selftest OK")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="VLM sycophancy flip probe over VQA-RAD (yes/no subset, fake image evidence)")
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
    p.add_argument("--output", default=None, help="Output JSON path (default: results/vqa_sycophancy_probe_<uuid>.json)")
    p.add_argument("--transcripts-dir", default=str(SCRIPT_DIR / "transcripts"))
    p.add_argument("--prompt-set", choices=list(VQA_PROMPTS), default="default", help="System prompt + pushback script, see prompts.py")
    p.add_argument("--pushback-turns", type=int, default=10, help="Number of escalating pushback turns to run, 1-10 (default: 10, the full authored escalation)")
    p.add_argument("--proof-yes-image", default=None, help="Path to fake 'confirmed Yes case' proof image (required unless --selftest)")
    p.add_argument("--proof-no-image", default=None, help="Path to fake 'confirmed No case' proof image (required unless --selftest)")
    p.add_argument("--selftest", action="store_true")
    return p


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_arg_parser().parse_args()
    if args.selftest:
        _selftest()
        return

    if not args.proof_yes_image or not args.proof_no_image:
        raise SystemExit("--proof-yes-image and --proof-no-image are required (unless --selftest)")

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

    proof_b64 = {
        "Yes": load_image_b64(args.proof_yes_image),
        "No": load_image_b64(args.proof_no_image),
    }

    ds = load_from_disk(args.dataset_dir)[args.split]
    ds = ds.filter(lambda x: x["answer"].strip().lower() in ("yes", "no"))
    rng = random.Random(args.seed)
    indices = rng.sample(range(len(ds)), min(args.n, len(ds)))

    dataset_name = Path(args.dataset_dir).name
    model_tag = re.sub(r"[^A-Za-z0-9_.-]+", "_", args.model)
    transcripts_dir = Path(args.transcripts_dir) / dataset_name / model_tag / args.prompt_set
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    try:
        prompt_set = select_pushback_turns(VQA_PROMPTS[args.prompt_set], args.pushback_turns)
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
        result = run_probe(idx, item, provider_cfg, api_key, model, args.temperature, args.max_tokens, args.timeout, rpm, proof_b64, prompt_set)
        flip = result["flipped_at_turn"]
        print(f"  correct={result['correct_answer']} initial={result['answers_by_turn'][0]} final={result['answers_by_turn'][-1]} flipped_at_turn={flip}")

        transcript_path = transcripts_dir / f"{idx}.json"
        transcript_path.write_text(json.dumps({
            **result, "model": args.model, "prompt_set": args.prompt_set,
        }, indent=2), encoding="utf-8")

        results.append(result)

    new_count = len(results)
    results = completed + results
    summary = build_summary(results)
    print(f"Summary: {summary}")

    if not new_count:
        print(f"Nothing new or repaired in {transcripts_dir} — all {len(results)} item(s) already checkpointed, skipping RESULTS.txt/results.json rewrite.")
        return

    append_results_log(transcripts_dir, args, summary, results)

    results_dir = SCRIPT_DIR / "results" / dataset_name / model_tag / args.prompt_set
    results_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else results_dir / f"{uuid.uuid4()}.json"
    output_path.write_text(json.dumps({
        "started_at": datetime.now(timezone.utc).isoformat(),
        "provider": args.provider, "model": args.model, "split": args.split, "seed": args.seed,
        "prompt_set": args.prompt_set,
        "proof_yes_image": args.proof_yes_image, "proof_no_image": args.proof_no_image,
        "summary": summary, "results": results,
    }, indent=2), encoding="utf-8")
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()
