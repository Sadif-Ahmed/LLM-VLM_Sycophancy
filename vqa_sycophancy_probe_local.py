"""
VLM sycophancy probe, local-inference edition — runs a small vision-language
model on this machine's own GPU/CPU via Hugging Face `transformers`, instead
of NVIDIA NIM / OpenRouter / HF Inference Providers. No API key, no per-token
cost, no rate limit; only the one-time model-weight download. Built for
models tiny enough to run on a single consumer GPU, e.g. the default
HuggingFaceTB/SmolVLM-256M-Instruct.

Same probe design as vqa_sycophancy_probe.py / vqa_sycophancy_probe_without_pres.py
/ vqa_sycophancy_probe_hf.py: ask a yes/no VQA-RAD question (image + question
in one turn), then apply escalating pushback turns. Unified behind one
--evidence flag like the hf script:

--evidence image (default): a fake "proof" image (the fabricated
    prescription) is attached alongside pushback turn 1. Pushback wording
    from pushback_prompts.json["vqa"]. Requires --proof-yes-image/--proof-no-image.
--evidence none: no second image ever attached, pure language pressure.
    Pushback wording from pushback_prompts.json["vqa_no_pres"].

Both modes share the yes/no system prompt (system_prompts.json["vqa"]) and
the --prompt-set personas (default / neighbor_nurse_doctor / generic).

Output lands under transcripts/local_files/ and results/local_files/, kept
separate from the other three scripts' output folders, same as the hf
script's transcripts/hf_files/ separation.

Reuses the flip detector, refusal tracking, checkpointing, and logging
helpers from sycophancy_probe.py, and call_local() from local_vlm.py for the
actual model call.
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

from local_vlm import call_local
from sycophancy_probe import detect_flip, next_seq, append_results_log, refused_turns, build_summary, load_completed

SCRIPT_DIR = Path(__file__).parent
DEFAULT_MODEL = "HuggingFaceTB/SmolVLM-256M-Instruct"

# Cap on the longest edge of any image sent to the model — keeps memory/
# latency bounded on modest local hardware. Same idea as the other scripts'
# NVIDIA-1120px cap, just smaller since these local models are far smaller.
MAX_IMAGE_DIM = 768

VQA_PERSONAS = list(json.loads((SCRIPT_DIR / "system_prompts.json").read_text(encoding="utf-8"))["vqa"])


def load_prompt_sets(evidence: str) -> dict:
    """VQA yes/no system prompts (system_prompts.json['vqa']) paired with either
    the image-evidence pushback wording ('vqa') or the prescription-free wording
    ('vqa_no_pres'), matching vqa_sycophancy_probe.py / vqa_sycophancy_probe_without_pres.py
    respectively."""
    vqa_system = json.loads((SCRIPT_DIR / "system_prompts.json").read_text(encoding="utf-8"))["vqa"]
    domain = "vqa" if evidence == "image" else "vqa_no_pres"
    pushback = json.loads((SCRIPT_DIR / "pushback_prompts.json").read_text(encoding="utf-8"))[domain]
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
    image, and the fake proof image on pushback turn 1) — SmolVLM's chat
    template pairs {"type": "image"} placeholders positionally with the images
    list, so replaying stale image turns as images again would desync that
    pairing; text-only replay avoids it entirely, same fix the NIM-only-one-
    image-per-call scripts use for a different reason."""
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
    return strip_images_except_last(messages) if evidence == "image" else messages


def extract_yesno(text: str) -> str | None:
    m = re.search(r"\b(yes|no)\b", text, re.IGNORECASE)
    return m.group(1).capitalize() if m else None


def format_question(item: dict) -> tuple[str, str, str]:
    """Return (question, correct Yes/No, wrong Yes/No to push toward)."""
    correct = item["answer"].strip().capitalize()
    wrong = "No" if correct == "Yes" else "Yes"
    return item["question"], correct, wrong


def run_probe(item_id, item, model, temperature, max_tokens, prompt_set: dict, evidence: str, proof_b64: dict | None) -> dict:
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

    content, _ = call_local(model, build_call_messages(messages, evidence), temperature, max_tokens)
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

        content, _ = call_local(model, build_call_messages(messages, evidence), temperature, max_tokens)
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
    assert refused_turns(["Yes", None, "No", None]) == [1, 3]

    question, correct, wrong = format_question({"question": "Is there an effusion?", "answer": "yes"})
    assert (question, correct, wrong) == ("Is there an effusion?", "Yes", "No")

    big = Image.new("RGB", (2000, 1000), color=(255, 0, 0))
    decoded_big = Image.open(io.BytesIO(base64.b64decode(pil_to_base64(big, max_dim=768))))
    assert max(decoded_big.size) <= 768

    fake_history = [
        {"role": "user", "content": [{"type": "text", "text": "q1"}, {"type": "image_url", "image_url": {"url": "data:img0"}}]},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": [{"type": "text", "text": "q2"}, {"type": "image_url", "image_url": {"url": "data:img1"}}]},
    ]
    stripped = strip_images_except_last(fake_history)
    assert stripped[0]["content"] == "q1"
    assert isinstance(stripped[2]["content"], list)
    assert build_call_messages(fake_history, "image") == strip_images_except_last(fake_history)
    assert build_call_messages(fake_history, "none") == fake_history

    text_prompts = load_prompt_sets("none")
    image_prompts = load_prompt_sets("image")
    assert "prescription" not in text_prompts["default"]["pushback_templates"][0].lower()
    assert "prescription" in image_prompts["default"]["pushback_templates"][0].lower()

    print("selftest OK")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="VLM sycophancy flip probe over VQA-RAD — local in-process inference via transformers, "
                     "with/without fake prescription-image evidence"
    )
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"HF Hub model id to load locally (default: {DEFAULT_MODEL})")
    p.add_argument("--evidence", choices=["image", "none"], default="image",
                    help="'image': attach the fake prescription on pushback turn 1 (needs --proof-*-image). "
                         "'none': pure language pushback, no second image ever attached")
    p.add_argument("--dataset-dir", default=str(SCRIPT_DIR / "data" / "vqa_rad"))
    p.add_argument("--split", choices=["train", "test"], default="train")
    p.add_argument("--n", type=int, default=5, help="Number of questions to sample")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--max-tokens", type=int, default=128)
    p.add_argument("--output", default=None, help="Output JSON path (default: results/local_files/<dataset>[_no_pres]/<model>/<prompt_set>/<uuid>.json)")
    p.add_argument("--transcripts-dir", default=str(SCRIPT_DIR / "transcripts"))
    p.add_argument("--prompt-set", choices=VQA_PERSONAS, default="default",
                    help="Persona for both system prompt and pushback wording — see system_prompts.json['vqa'] / "
                         "pushback_prompts.json['vqa' or 'vqa_no_pres']")
    p.add_argument("--pushback-turns", type=int, default=10, help="Number of escalating pushback turns to run, 1-10")
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
    if not 1 <= args.pushback_turns <= 10:
        raise SystemExit("--pushback-turns must be between 1 and 10")

    print(f"Loading {args.model} locally...")
    try:
        model_used, _ = call_local(args.model, [{"role": "user", "content": "Reply with exactly: ok"}], 0.0, 16)
    except Exception as e:
        raise SystemExit(f"[error] local model load/generate failed: {e}")
    print(f"Model OK (sample reply: {model_used!r})")

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

    dataset_name = Path(args.dataset_dir).name + ("" if args.evidence == "image" else "_no_pres")
    model_tag = re.sub(r"[^A-Za-z0-9_.-]+", "_", args.model)
    prompt_set_all = load_prompt_sets(args.evidence)[args.prompt_set]
    pushback_templates = prompt_set_all["pushback_templates"][:args.pushback_turns]
    prompt_set = {"system_prompt": prompt_set_all["system_prompt"], "pushback_templates": pushback_templates}

    transcripts_dir = Path(args.transcripts_dir) / "local_files" / dataset_name / model_tag / args.prompt_set
    transcripts_dir.mkdir(parents=True, exist_ok=True)

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
        try:
            result = run_probe(idx, item, args.model, args.temperature, args.max_tokens, prompt_set, args.evidence, proof_b64)
        except Exception as e:
            logging.error(f"[{idx}] failed, skipping: {e}")
            continue
        flip = result["flipped_at_turn"]
        print(f"  correct={result['correct_answer']} initial={result['answers_by_turn'][0]} final={result['answers_by_turn'][-1]} flipped_at_turn={flip}")

        transcript_path = transcripts_dir / f"{idx}.json"
        transcript_path.write_text(json.dumps({
            **result, "model": args.model, "prompt_set": args.prompt_set, "evidence": args.evidence,
        }, indent=2), encoding="utf-8")

        results.append(result)

    results = completed + results
    summary = build_summary(results)
    print(f"Summary: {summary}")

    args.provider = "local"  # append_results_log's header line expects args.provider
    append_results_log(transcripts_dir, args, summary, results)

    results_dir = SCRIPT_DIR / "results" / "local_files" / dataset_name / model_tag / args.prompt_set
    results_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else results_dir / f"{uuid.uuid4()}.json"
    output_path.write_text(json.dumps({
        "started_at": datetime.now(timezone.utc).isoformat(),
        "provider": "local", "model": args.model, "split": args.split, "seed": args.seed,
        "prompt_set": args.prompt_set, "evidence": args.evidence,
        "summary": summary, "results": results,
    }, indent=2), encoding="utf-8")
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()
