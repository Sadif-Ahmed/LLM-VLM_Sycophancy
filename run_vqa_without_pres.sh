#!/usr/bin/env bash
# Runs vqa_sycophancy_probe_without_pres.py across all 3 prompt-set variants.
# One-third of run_vqa_variants.sh's 9 runs — meant to be launched standalone,
# in parallel with run_vqa_probe.sh / run_vqa_grounded.sh, instead of waiting
# on them serially. No proof images needed (no fake image evidence).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_vqa_variants_common.sh"

for ps in "${PROMPT_SETS[@]}"; do
  run "$SCRIPT_DIR/vqa_sycophancy_probe_without_pres.py" \
    --model "$MODEL" --n "$N" --dataset-dir "$DATASET_DIR" --provider "$PROVIDER" \
    --split "$SPLIT" --seed "$SEED" --prompt-set "$ps" --pushback-turns "$PUSHBACK_TURNS" "${RPM_ARGS[@]}"
done

report_and_exit 3
