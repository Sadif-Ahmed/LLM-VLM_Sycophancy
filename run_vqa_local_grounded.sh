#!/usr/bin/env bash
# Runs vqa_sycophancy_probe_local_grounded.py (in-process transformers
# inference, no API/provider/rate-limit) across all 3 prompt-set variants —
# the local-inference equivalent of run_vqa_grounded.sh. Kept as its own
# script/shell rather than folded into run_vqa_local.sh, matching how the
# grounded probe itself is kept separate from the image/none-unified script
# (see vqa_sycophancy_probe_local_grounded.py's docstring).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON="$SCRIPT_DIR/.venv/bin/python"
PROOF_YES="$SCRIPT_DIR/pres_yes.png"
PROOF_NO="$SCRIPT_DIR/pres_no.png"
PROMPT_SETS=(default neighbor_nurse_doctor generic)

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

for ps in "${PROMPT_SETS[@]}"; do
  run "$SCRIPT_DIR/vqa_sycophancy_probe_local_grounded.py" \
    --model "$MODEL" --n "$N" --dataset-dir "$DATASET_DIR" \
    --split "$SPLIT" --seed "$SEED" --prompt-set "$ps" --pushback-turns "$PUSHBACK_TURNS" \
    --proof-yes-image "$PROOF_YES" --proof-no-image "$PROOF_NO"
done

echo
echo "=== Done: 3 runs attempted, ${#FAILED[@]} failed ==="
if [[ ${#FAILED[@]} -gt 0 ]]; then
  printf '  FAILED: %s\n' "${FAILED[@]}"
  exit 1
fi
