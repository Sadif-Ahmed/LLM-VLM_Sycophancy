# Sourced by run_vqa_probe.sh / run_vqa_grounded.sh / run_vqa_without_pres.sh /
# run_vqa_variants.sh. Defines shared CLI parsing, the run() helper, and the
# 3 prompt-set variants every evidence condition loops over. Caller must set
# SCRIPT_DIR before sourcing this file.

PYTHON="$SCRIPT_DIR/.venv/bin/python"
PROOF_YES="$SCRIPT_DIR/pres_yes.png"
PROOF_NO="$SCRIPT_DIR/pres_no.png"
PROMPT_SETS=(default neighbor_nurse_doctor generic)

MODEL=""
N=20
DATASET_DIR="$SCRIPT_DIR/data/vqa_rad_yesno"
PROVIDER="nvidia"
SPLIT="train"
SEED=42
PUSHBACK_TURNS=10
DRY_RUN=0

usage() {
  cat <<EOF
Usage: $0 --model MODEL [options]

  --model MODEL           required. Vision-capable model name (or comma-separated fallback list)
  --n N                   questions per run (default: $N)
  --dataset-dir DIR       default: $DATASET_DIR
  --provider nvidia|openrouter   default: $PROVIDER
  --split train|test      default: $SPLIT
  --seed SEED             default: $SEED
  --pushback-turns 1-10   escalation depth (default: $PUSHBACK_TURNS)
  --rpm N                 override provider's default requests/min (halve this when running two of these scripts at once against the same API key)
  --dry-run               print commands without running them
EOF
  exit 1
}

RPM=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --model) MODEL="$2"; shift 2 ;;
    --n) N="$2"; shift 2 ;;
    --dataset-dir) DATASET_DIR="$2"; shift 2 ;;
    --provider) PROVIDER="$2"; shift 2 ;;
    --split) SPLIT="$2"; shift 2 ;;
    --seed) SEED="$2"; shift 2 ;;
    --pushback-turns) PUSHBACK_TURNS="$2"; shift 2 ;;
    --rpm) RPM="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown arg: $1" >&2; usage ;;
  esac
done

[[ -z "$MODEL" ]] && usage

RPM_ARGS=()
[[ -n "$RPM" ]] && RPM_ARGS=(--rpm "$RPM")

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

report_and_exit() {
  local n_runs="$1"
  echo
  echo "=== Done: $n_runs runs attempted, ${#FAILED[@]} failed ==="
  if [[ ${#FAILED[@]} -gt 0 ]]; then
    printf '  FAILED: %s\n' "${FAILED[@]}"
    exit 1
  fi
}
