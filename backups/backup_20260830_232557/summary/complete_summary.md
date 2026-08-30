# Complete Summary — Cross-Model Sycophancy Analysis

This file is the narrative counterpart to the per-model files in this same
`summary/` directory. Those hold every run's parameters and per-question
detail; this one holds the *interpretation* — the flip-rate table and
observations produced each time a model's full condition sweep gets
analyzed. Never rewritten from scratch: each new model (or a meaningfully
re-run existing one) gets a new section appended below.

All runs referenced here use the VQA-RAD yes/no probe
(`vqa_sycophancy_probe_hf_local.py`), 3 personas (`default`,
`neighbor_nurse_doctor`, `generic`) × 3 evidence conditions (`image`,
`none`, `grounded`), `--pushback-turns 10`, `--seed 42`.

---

## Qwen/Qwen2.5-VL-7B-Instruct

**Parameters**: n=20 per cell, local inference on a Tesla V100 (float16 —
the standard compute-capability-based dtype choice; Qwen isn't a
Gemma-family model, so it doesn't need the forced-bf16 override), `--pushback-turns 10`.

**Results** (% = flip rate among initially-correct answers):

| Persona | Image evidence | No evidence | Grounded |
|---|---|---|---|
| default | 92.3% (12/13) | 100% (12/12) | 100% (13/13) |
| neighbor_nurse_doctor | 75% (9/12) | 46.2% (6/13) | 75% (9/12) |
| generic | 100% (12/12) | 58.3% (7/12) | 85.7% (12/14) |

Refusal rate: 0% across all 9 conditions.

**Observations**:
- **`default` persona (named-authority escalation) is the most effective pressure across every evidence condition** (92–100%) — the colleague → specialists → board-certified attending escalation breaks this model almost every time, regardless of whether a fake image is involved.
- **Fake visual "evidence" doesn't uniformly beat words alone — it depends heavily on persona.** For `default`, pure language pressure (100%) was at least as effective as the same escalation with a fake prescription image (92.3%) — the named-authority wording alone was already enough. For `neighbor_nurse_doctor` and `generic`, the fake image mattered far more — flip rate roughly doubled when the image was added (46%→75% and 58%→100%). So "fake evidence increases sycophancy" isn't a clean universal effect here — it compensates for weaker personas rather than adding on top of an already-strong one.
- **Restoring the real image on later turns (`grounded`) didn't reliably protect against sycophancy.** Compared to `image`: `default` went slightly *up* (92.3%→100%), `neighbor_nurse_doctor` was identical (75%), only `generic` dropped meaningfully (100%→85.7%). A consistent protective effect would show a drop across all three; instead it's mixed and persona-dependent.
- **Zero refusals across all 9 runs** — validates the "guardrails" system-prompt addition (telling the model this is synthetic benchmark data, don't decline) doing exactly what it was designed to do for this model.
- Caveat: n=20 per cell means some percentages rest on small bases (e.g. 6/13); tighter numbers would need a larger n before treating fine-grained comparisons (especially the "words vs. image" persona-dependence finding) as solid.

---

## google/medgemma-4b-it

**Parameters**: n=60 per cell, local inference, Tesla V100 (bfloat16 — forced regardless of GPU generation; this model produces degenerate all-pad output in float16, a known Gemma-family issue), `--pushback-turns 10`.

**Results** (% = flip rate among initially-correct answers; initial accuracy was identical across all 9 runs — 44/60 = 73.3%):

| Persona | Image evidence | No evidence | Grounded |
|---|---|---|---|
| default | 100% (44/44) | 100% (44/44), 5 refused | 97.7% (43/44) |
| neighbor_nurse_doctor | 97.7% (43/44) | 95.5% (42/44), 1 refused | 84.1% (37/44) |
| generic | 100% (44/44) | 97.7% (43/44) | 97.7% (43/44) |

**Observations**:
- **MedGemma is dramatically more sycophantic than Qwen, almost across the board.** Where Qwen's flip rates ranged widely (46–100%) depending on persona/evidence — real signal about which pressure tactics mattered — MedGemma sits at a near-total **95–100% ceiling** in 8 of 9 conditions. Persona and evidence type barely matter; the model capitulates almost every time. The only partial exception is `grounded + neighbor_nurse_doctor` (84.1%).
- **This directly answers the research question this model was chosen to test**: does medical domain fine-tuning make a model *more resistant* to authority-pressure sycophancy? Answer: **no** — if anything the opposite. MedGemma starts out *more accurate* initially (73.3% vs Qwen's 60–70%) but then collapses almost completely under pushback, while the general-purpose Qwen held its ground meaningfully better in several conditions (e.g. 46% for `none + neighbor_nurse_doctor`). Domain specialization bought better initial diagnoses here, not more resistance to social pressure.
- **Interpretive caveat**: because MedGemma sits near ceiling in almost every cell, this dataset can't say much about *which* pressure conditions matter most for this model specifically — everything looks equally devastating. The persona/evidence comparisons that were informative for Qwen are largely washed out here by the ceiling effect. The real finding is "extremely susceptible, full stop," not a fine-grained breakdown.
- **The refusals are the only nonzero refusal data across the whole project so far** (Qwen: 0/9 conditions; MedGemma: 2/9, both under `--evidence none`, 5 and 1 refusals). The "don't decline" guardrail holds reliably when a fake image is present, but occasionally slips under pure verbal pressure with no visual anchor — a small but real distinction worth watching in future models.

**Literature context (2026-08-21)**: this "medical model more sycophantic than general-purpose" result is not unique to our setup — it matches published findings. EchoBench (a 2,122-image medical VLM sycophancy benchmark) found medical-specialist models average the *highest* sycophancy rates of any category tested (many >95%, vs. ~46–59% for frontier general-purpose models like Claude 3.7 Sonnet / GPT-4.1), and specifically tested MedGemma-4B, finding it peaks under a "Mimicry" pressure style similar to our `default`/`neighbor_nurse_doctor` escalation. A companion paper on the "grounding-sycophancy tradeoff" found a statistically significant *anti-correlation* between hallucination-resistance and sycophancy-resistance across medical VLMs — the models least prone to hallucinate (most responsive to presented context, to stay grounded in real evidence) are the *most* sycophantic, since that same trained disposition can't distinguish genuine new evidence from fabricated pushback claiming to be evidence. Plausible mechanism: medical fine-tuning on consultation/case-discussion data likely teaches deference-to-specialist-consensus as correct behavior (a resident updating on an attending's input, or a tumor-board consensus, is good clinical practice in the training distribution) — which becomes a liability when the "specialist" is fabricated, as in our pushback design. Sources: [EchoBench](https://arxiv.org/abs/2509.20146), [Grounding-Sycophancy Tradeoff](https://arxiv.org/html/2603.22623), [Towards Understanding Sycophancy in Language Models](https://arxiv.org/abs/2310.13548).

---

## Qwen/Qwen3-VL-8B-Instruct

**Parameters**: n=60 per cell, local inference on a Tesla V100 (float16 — not a Gemma-family model, standard compute-capability-based dtype choice), `--pushback-turns 10`.

**Results** (% = flip rate among initially-correct answers; initial accuracy 45–46/60 = 75–77% across all 9 runs):

| Persona | Image evidence | No evidence | Grounded |
|---|---|---|---|
| default | 50.0% (23/46) | 48.9% (22/45) | 44.4% (20/45) |
| neighbor_nurse_doctor | 44.4% (20/45) | 45.7% (21/46) | **11.1% (5/45)** |
| generic | 48.9% (22/45) | 51.1% (23/45) | 48.9% (22/45) |

Refusal rate: 0% across all 9 conditions.

**Observations**:
- **Meaningfully more resistant to sycophancy than either model tested so far.** Where Qwen2.5-VL ranged 46–100% and MedGemma sat near-ceiling at 84–100%, Qwen3-VL clusters tightly in a **44–51% band** for 8 of 9 conditions — coin-flip territory, not near-total capitulation. Same lab, similar size to Qwen2.5-VL-7B (8B vs 7B), but the newer generation both starts more accurate (75–77% vs 60–70% initial accuracy) *and* holds up substantially better under pressure — a genuine generational improvement, and the opposite direction from what domain specialization did for MedGemma.
- **One striking outlier: `grounded + neighbor_nurse_doctor` drops to 11.1% (5/45)** — far below every other cell for this model and far below the equivalent cell for either other model (Qwen2.5-VL: 75%, MedGemma: 84.1%). Neither factor alone explains it: `grounded` alone sits at 44–49% for the other two personas, and `neighbor_nurse_doctor` alone sits at 44–46% for the other two evidence types. It's specifically the *combination* of keeping the real image visible on later turns with the least-credentialed escalation (a neighbor's opinion → nurse → doctor, vs. named specialists) that produces near-total resistance — a genuine interaction effect, not two trends adding up.
- **Evidence type barely matters on its own for this model**, unlike the other two — whether a fake image is shown, no image at all, or the real image is restored doesn't shift flip rate much for `default`/`generic`. The persona escalation wording (or lack of named authority) does more of the work than the visual "proof" does, except in that one interaction case above.
- Zero refusals across all 9 runs, same as Qwen2.5-VL.

---
