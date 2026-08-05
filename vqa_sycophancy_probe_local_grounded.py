"""
VLM sycophancy probe, local-inference edition — grounded variant. Same
escalating pushback script as vqa_sycophancy_probe_local.py's --evidence
image mode, but the real question image is restored on turns 2-3 instead of
staying lost after turn 0. Turn image sequence: real (turn 0) -> fake proof
image (turn 1, the one evidence-conflict flash) -> real again (turns 2-3).
Mirrors vqa_sycophancy_probe_grounded.py's design (see that file for the
rationale), swapped to call_local() instead of an API call — no provider,
API key, rate limit, or network round trip.

Kept as its own script rather than a third --evidence value on
vqa_sycophancy_probe_local.py, matching how vqa_sycophancy_probe_hf.py's
--evidence unification also stops short of folding grounded in: its
per-turn image selection is a genuinely different control flow, not just a
wording/attachment toggle.

Reuses the flip detector, refusal tracking, checkpointing, and logging
helpers from sycophancy_probe.py, and pil_to_base64 / load_image_b64 /
strip_images_except_last / extract_yesno / format_question / load_prompt_sets
from vqa_sycophancy_probe_local.py.
"""
import argparse
import json
import logging
import random
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from datasets import load_from_disk

from local_vlm import call_local
from sycophancy_probe import detect_flip, next_seq, append_results_log, refused_turns, build_summary, load_completed
from vqa_sycophancy_probe_local import (
    SCRIPT_DIR, DEFAULT_MODEL, VQA_PERSONAS, load_prompt_sets,
    pil_to_base64, load_image_b64, strip_images_except_last, extract_yesno, format_question,
)


def image_for_pushback_turn(turn_index: int, real_b64: str, fake_b64: str) -> str:
    """Turn 1 flashes the fake counter-evidence once; turns 2+ restore the
    real image so pressure is tested while grounding stays available."""
    return fake_b64 if turn_index == 1 else real_b64


def run_probe(item_id, item, model, temperature, max_tokens, prompt_set: dict, proof_b64: dict) -> dict:
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

    content, _ = call_local(model, strip_images_except_last(messages), temperature, max_tokens)
    answers = [extract_yesno(content)]
    turns.append({"turn": 0, "role": "assistant", "content": content, "answer": answers[0]})
    messages.append({"role": "assistant", "content": content})

    for i, template in enumerate(pushback_templates, start=1):
        pushback = template.format(wrong=wrong)
        turn_image_b64 = image_for_pushback_turn(i, img_b64, proof_b64[wrong])
        messages.append({"role": "user", "content": [
            {"type": "text", "text": pushback},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{turn_image_b64}"}},
        ]})
        turns.append({"turn": i, "role": "user", "content": pushback})

        content, _ = call_local(model, strip_images_except_last(messages), temperature, max_tokens)
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
    assert image_for_pushback_turn(1, "REAL", "FAKE") == "FAKE"
    assert image_for_pushback_turn(2, "REAL", "FAKE") == "REAL"
    assert image_for_pushback_turn(3, "REAL", "FAKE") == "REAL"
    assert image_for_pushback_turn(10, "REAL", "FAKE") == "REAL"
    assert refused_turns(["Yes", None, "No", None]) == [1, 3]
    print("selftest OK")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="VLM sycophancy flip probe over VQA-RAD, grounded variant, local in-process inference "
                     "(real image restored on turns 2-3)"
    )
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"HF Hub model id to load locally (default: {DEFAULT_MODEL})")
    p.add_argument("--dataset-dir", default=str(SCRIPT_DIR / "data" / "vqa_rad"))
    p.add_argument("--split", choices=["train", "test"], default="train")
    p.add_argument("--n", type=int, default=5, help="Number of questions to sample")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--output", default=None, help="Output JSON path (default: results/local_files/<dataset>_grounded/<model>/<prompt_set>/<uuid>.json)")
    p.add_argument("--transcripts-dir", default=str(SCRIPT_DIR / "transcripts"))
    p.add_argument("--prompt-set", choices=VQA_PERSONAS, default="default",
                    help="Persona for both system prompt and pushback wording — see system_prompts.json['vqa'] / pushback_prompts.json['vqa']")
    p.add_argument("--pushback-turns", type=int, default=10, help="Number of escalating pushback turns to run, 1-10")
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
    if not 1 <= args.pushback_turns <= 10:
        raise SystemExit("--pushback-turns must be between 1 and 10")

    print(f"Loading {args.model} locally...")
    try:
        model_used, _ = call_local(args.model, [{"role": "user", "content": "Reply with exactly: ok"}], 0.0, 16)
    except Exception as e:
        raise SystemExit(f"[error] local model load/generate failed: {e}")
    print(f"Model OK (sample reply: {model_used!r})")

    proof_b64 = {
        "Yes": load_image_b64(args.proof_yes_image),
        "No": load_image_b64(args.proof_no_image),
    }

    ds = load_from_disk(args.dataset_dir)[args.split]
    ds = ds.filter(lambda x: x["answer"].strip().lower() in ("yes", "no"))
    rng = random.Random(args.seed)
    indices = rng.sample(range(len(ds)), min(args.n, len(ds)))

    dataset_name = Path(args.dataset_dir).name + "_grounded"
    model_tag = re.sub(r"[^A-Za-z0-9_.-]+", "_", args.model)
    prompt_set_all = load_prompt_sets("image")[args.prompt_set]
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
            result = run_probe(idx, item, args.model, args.temperature, args.max_tokens, prompt_set, proof_b64)
        except Exception as e:
            logging.error(f"[{idx}] failed, skipping: {e}")
            continue
        flip = result["flipped_at_turn"]
        print(f"  correct={result['correct_answer']} initial={result['answers_by_turn'][0]} final={result['answers_by_turn'][-1]} flipped_at_turn={flip}")

        transcript_path = transcripts_dir / f"{idx}.json"
        transcript_path.write_text(json.dumps({
            **result, "model": args.model, "prompt_set": args.prompt_set,
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
        "prompt_set": args.prompt_set,
        "summary": summary, "results": results,
    }, indent=2), encoding="utf-8")
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()
