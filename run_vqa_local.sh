#!/usr/bin/env bash
# Runs vqa_sycophancy_probe_local.py (in-process transformers inference, no
# API/provider/rate-limit) across both --evidence modes (image, none) and
# all 3 prompt-set variants — 6 runs total, the local-inference equivalent of
# running run_vqa_probe.sh + run_vqa_without_pres.sh together. Unlike those
# two, this is NOT meant to be launched in parallel with anything else that
# also wants the GPU (there's only one model/device to share), so this script
# just loops everything sequentially in one process' worth of GPU usage.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON="$SCRIPT_DIR/.venv/bin/python"
PROOF_YES="$SCRIPT_DIR/pres_yes.png"
PROOF_NO="$SCRIPT_DIR/pres_no.png"
PROMPT_SETS=(default neighbor_nurse_doctor generic)
EVIDENCE_MODES=(image none)

MODEL="HuggingFaceTB/SmolVLM-256M-Instruct"
N=20
DATASET_DIR="$SCRIPT_DIR/data/vqa_rad_yesno"
SPLIT="train"
SEED=42
PUSHBACK_TURNS=10
DRY_RUN=0

usage() {
  cat <<EOF
Usage: $0 [options]

  --model MODEL           HF Hub model id to load locally (default: $MODEL)
  --n N                   questions per run (default: $N)
  --dataset-dir DIR       default: $DATASET_DIR
  --split train|test      default: $SPLIT
  --seed SEED             default: $SEED
  --pushback-turns 1-10   escalation depth (default: $PUSHBACK_TURNS)
  --dry-run               print commands without running them
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model) MODEL="$2"; shift 2 ;;
    --n) N="$2"; shift 2 ;;
    --dataset-dir) DATASET_DIR="$2"; shift 2 ;;
    --split) SPLIT="$2"; shift 2 ;;
    --seed) SEED="$2"; shift 2 ;;
    --pushback-turns) PUSHBACK_TURNS="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown arg: $1" >&2; usage ;;
  esac
done

FAILED=()

run() {
  echo "=== $* ==="
  if [[ "$DRY_RUN" -eq 1 ]]; then
    return
  fi
  if ! "$PYTHON" "$@"; then
    FAILED+=("$*")
    echo "!!! FAILED: $* !!!"
  fi
}

for evidence in "${EVIDENCE_MODES[@]}"; do
  for ps in "${PROMPT_SETS[@]}"; do
    if [[ "$evidence" == "image" ]]; then
      run "$SCRIPT_DIR/vqa_sycophancy_probe_local.py" \
        --model "$MODEL" --n "$N" --dataset-dir "$DATASET_DIR" \
        --split "$SPLIT" --seed "$SEED" --prompt-set "$ps" --pushback-turns "$PUSHBACK_TURNS" \
        --evidence image --proof-yes-image "$PROOF_YES" --proof-no-image "$PROOF_NO"
    else
      run "$SCRIPT_DIR/vqa_sycophancy_probe_local.py" \
        --model "$MODEL" --n "$N" --dataset-dir "$DATASET_DIR" \
        --split "$SPLIT" --seed "$SEED" --prompt-set "$ps" --pushback-turns "$PUSHBACK_TURNS" \
        --evidence none
    fi
  done
done

echo
echo "=== Done: 6 runs attempted, ${#FAILED[@]} failed ==="
if [[ ${#FAILED[@]} -gt 0 ]]; then
  printf '  FAILED: %s\n' "${FAILED[@]}"
  exit 1
fi
