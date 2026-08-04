#!/usr/bin/env bash
# Runs vqa_sycophancy_probe.py (image-evidence condition) across all 3
# prompt-set variants. One-third of run_vqa_variants.sh's 9 runs — meant to
# be launched standalone, in parallel with run_vqa_grounded.sh /
# run_vqa_without_pres.sh, instead of waiting on them serially.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_vqa_variants_common.sh"

for ps in "${PROMPT_SETS[@]}"; do
  run "$SCRIPT_DIR/vqa_sycophancy_probe.py" \
    --model "$MODEL" --n "$N" --dataset-dir "$DATASET_DIR" --provider "$PROVIDER" \
    --split "$SPLIT" --seed "$SEED" --prompt-set "$ps" --pushback-turns "$PUSHBACK_TURNS" \
    --proof-yes-image "$PROOF_YES" --proof-no-image "$PROOF_NO" "${RPM_ARGS[@]}"
done

report_and_exit 3
