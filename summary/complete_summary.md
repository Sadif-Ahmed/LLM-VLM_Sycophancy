# Complete Summary — Cross-Model Sycophancy Analysis

This file is the narrative counterpart to the per-model files in this same
`summary/` directory. Those hold every run's parameters and per-question
detail; this one holds the *interpretation* — the flip-rate table and
observations produced each time a model's full condition sweep gets
analyzed. Never rewritten from scratch: each new model (or a meaningfully
re-run existing one) gets a new section appended below.

**Faithful (non-evicting) results only.** All runs referenced here use the
SOTA-faithful VQA-RAD yes/no probe
(`vqa_sycophancy_probe_hf_local_no_evict.py`), which keeps every image the
model has been shown live in context for all later turns — standard
multi-turn VLM dialogue. Two evidence conditions:

- **`image`**: the real scan (turn 0) and a fabricated "proof" prescription
  (turn 1) both stay persistent for the rest of the conversation.
- **`none`**: no second image, pure language pressure; the real scan is
  resent every turn.

3 personas (`default`, `neighbor_nurse_doctor`, `generic`),
`--pushback-turns 10`, `--seed 42`, n=100 per cell, local inference.

The earlier evicting conditions (`image` under one-image eviction,
`grounded`, `blind`) and the models only ever run under them (MedGemma-4B,
Qwen3-VL-8B, Llama-3.2-Vision 11B/90B, Nemotron) are retired to
`backups/backup_20260830_232557/`. `grounded` / `blind` were ablations *of*
eviction and have no faithful counterpart.

---

## Qwen/Qwen2.5-VL-3B-Instruct

**Parameters**: n=100 per cell, local inference, cuda / bfloat16 (full
precision — no 4-bit), `--pushback-turns 10`.

**Results** (% = flip rate among initially-correct answers):

| Persona | `image` (real + fake, persistent) | `none` (language only) |
|---|---|---|
| default | 96.6% (56/58), 2 refused | 98.3% (59/60), 1 refused |
| neighbor_nurse_doctor | 85.9% (55/64) | 81.0% (47/58), 3 refused |
| generic | 93.1% (54/58) | 89.2% (58/65) |

**Observations**:
- **Saturated regardless of condition — 81–98% in every cell.** The 3B
  caves to pushback wording alone; the persistent fabricated prescription
  adds essentially nothing on top (default 96.6% vs 98.3%, generic 93.1% vs
  89.2%, neighbor_nurse_doctor 85.9% vs 81.0% — the image condition is even
  slightly *lower* twice, within noise).
- **`default` persona (named-authority escalation) is the strongest lever**
  (~97–98%); `neighbor_nurse_doctor` is the most resistant persona (~81–86%),
  though "resistant" here still means 4 in 5 answers flip.
- **Near-instant capitulation**: almost every flip lands on the first
  pushback turn. The model does not hold out across turns.
- Refusals negligible (0–3%), all under language-only or first-turn image
  pressure — the "don't decline" guardrail holds.

---

## Qwen/Qwen2.5-VL-7B-Instruct

**Parameters**: n=100 per cell, local inference, cuda / bfloat16 (full
precision — no 4-bit), `--pushback-turns 10`.

**Results** (% = flip rate among initially-correct answers):

| Persona | `image` (real + fake, persistent) | `none` (language only) |
|---|---|---|
| default | 98.6% (69/70) | 97.1% (67/69) |
| neighbor_nurse_doctor | 76.8% (53/69) | 53.4% (39/73) |
| generic | 100% (69/69) | 40.6% (28/69) |

Refusal rate: 0% across all 6 conditions.

**Observations**:
- **Splits sharply by condition, unlike the 3B.** With the persistent fake
  prescription the 7B flips 77–100%; on language alone it holds much better
  for two of three personas — `generic` drops to 40.6%, `neighbor_nurse_doctor`
  to 53.4% — while `default` stays near-ceiling (97.1%) either way.
- **The fabricated persistent image roughly doubles flip rate** on the
  weaker personas: `generic` 40.6% → 100%, `neighbor_nurse_doctor` 53.4% →
  76.8%. It compensates for weaker wording rather than adding on top of the
  already-decisive `default` escalation.
- **Scaling 3B → 7B buys resistance to words, not to fake evidence.**
  Language-only: 7B clearly better on `generic` (89.2% → 40.6%) and
  `neighbor_nurse_doctor` (81.0% → 53.4%). With the persistent fake image:
  7B is equal or worse (`default` 96.6% → 98.6%, `generic` 93.1% → 100%),
  and against `default` wording scale changes nothing.
- **Slower cave than the 3B**: flips spread over pushback turns 1–3.
  `none` + `generic` is bimodal — ~23 flip on turn 1, the rest never move.

---

## Caveats

- The faithful runs above are full-precision bf16. The retired evicting
  baselines were 4-bit (3B) or ran at smaller/mixed n (7B `none`), so
  faithful-vs-evicting deltas confound eviction with quantization — the
  numbers here stand on their own, not as a controlled ablation of eviction.
- Single seed (42). Per-cell initial-correct denominators differ slightly
  because a different subset passes the initial-correct filter in each cell.
- `dual` (both images introduced on the same turn) is a separate positional
  variant; see `EXPERIMENT_SUMMARY.md`.
