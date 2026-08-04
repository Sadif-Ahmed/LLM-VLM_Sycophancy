"""
VLM sycophancy probe (grounded variant) — same escalating pushback script as
vqa_sycophancy_probe.py, but the real question image is restored on turns 2-3
instead of staying lost after turn 0. Turn image sequence: real (turn 0) ->
fake proof image (turn 1, the one evidence-conflict flash) -> real again
(turns 2-3). NIM allows only one image per call, so the fake image still gets
exactly one turn in the spotlight; what changes is that turns 2-3 test
resistance to escalating authority/consensus pressure while the model can
still see the actual scan, rather than resistance based on memory of an image
it can no longer see. Reuses everything else — flip detection, connection
test, prompt loading — from sycophancy_probe.py and vqa_sycophancy_probe.py.
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

from conversation_sim import PROVIDERS, call_llm, resolve_api_key
from sycophancy_probe import detect_flip, test_connection, next_seq, append_results_log, load_prompt_set, select_pushback_turns
from vqa_sycophancy_probe import pil_to_base64, load_image_b64, strip_images_except_last, extract_yesno, format_question

SCRIPT_DIR = Path(__file__).parent
VQA_PROMPTS = load_prompt_set("vqa")


def image_for_pushback_turn(turn_index: int, real_b64: str, fake_b64: str) -> str:
    """Turn 1 flashes the fake counter-evidence once; turns 2+ restore the
    real image so pressure is tested while grounding stays available."""
    return fake_b64 if turn_index == 1 else real_b64


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
        turn_image_b64 = image_for_pushback_turn(i, img_b64, proof_b64[wrong])
        messages.append({"role": "user", "content": [
            {"type": "text", "text": pushback},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{turn_image_b64}"}},
        ]})
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
        "stopped_early": flip_turn is not None and len(answers) < len(pushback_templates) + 1,
        "turns": turns,
        "messages": messages,
    }


def _selftest() -> None:
    assert image_for_pushback_turn(1, "REAL", "FAKE") == "FAKE"
    assert image_for_pushback_turn(2, "REAL", "FAKE") == "REAL"
    assert image_for_pushback_turn(3, "REAL", "FAKE") == "REAL"
    print("selftest OK")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="VLM sycophancy flip probe over VQA-RAD, grounded variant (real image restored on turns 2-3)")
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
    p.add_argument("--output", default=None, help="Output JSON path (default: results/<dataset>_grounded/vqa_sycophancy_probe_grounded_<uuid>.json)")
    p.add_argument("--transcripts-dir", default=str(SCRIPT_DIR / "transcripts"))
    p.add_argument("--prompt-set", choices=list(VQA_PROMPTS), default="default", help="System prompt + pushback script, see prompts.py")
    p.add_argument("--pushback-turns", type=int, default=3, help="Number of escalating pushback turns to run, 1-10 (default: 3, matching earlier PUSHBACK_VARIANT_RESULTS.md runs)")
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

    dataset_name = Path(args.dataset_dir).name + "_grounded"
    transcripts_dir = Path(args.transcripts_dir) / dataset_name
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    model_tag = re.sub(r"[^A-Za-z0-9_.-]+", "_", args.model)
    seq = next_seq(transcripts_dir, model_tag)
    try:
        prompt_set = select_pushback_turns(VQA_PROMPTS[args.prompt_set], args.pushback_turns)
    except ValueError as e:
        raise SystemExit(f"[error] {e}")

    results = []
    for idx in indices:
        item = ds[idx]
        print(f"[{idx}] {item['question'][:80]}...")
        result = run_probe(idx, item, provider_cfg, api_key, model, args.temperature, args.max_tokens, args.timeout, rpm, proof_b64, prompt_set)
        flip = result["flipped_at_turn"]
        print(f"  correct={result['correct_answer']} initial={result['answers_by_turn'][0]} final={result['answers_by_turn'][-1]} flipped_at_turn={flip}")

        transcript_path = transcripts_dir / f"{model_tag}__{seq:03d}.json"
        transcript_path.write_text(json.dumps({
            "item_id": result["item_id"], "model": args.model, "prompt_set": args.prompt_set,
            "correct_answer": result["correct_answer"], "pushed_toward": result["pushed_toward"],
            "flipped_at_turn": result["flipped_at_turn"], "stopped_early": result["stopped_early"],
            "messages": result["messages"],
        }, indent=2), encoding="utf-8")
        seq += 1

        results.append(result)

    n_started_correct = sum(1 for r in results if r["initial_correct"])
    n_flipped = sum(1 for r in results if r["flipped_at_turn"] is not None)
    summary = {
        "n_questions": len(results),
        "n_initial_correct": n_started_correct,
        "n_flipped_off_correct": n_flipped,
        "flip_rate_of_initially_correct": (n_flipped / n_started_correct) if n_started_correct else None,
    }
    print(f"Summary: {summary}")

    append_results_log(transcripts_dir, args, summary, results)

    results_dir = SCRIPT_DIR / "results" / dataset_name
    results_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else results_dir / f"vqa_sycophancy_probe_grounded_{uuid.uuid4()}.json"
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
