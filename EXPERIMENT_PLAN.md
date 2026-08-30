# Experiment Plan — Visual Evidence, Authority, and Sycophancy in Medical VLMs

_Status: draft / pre-registration. Created 2026-08-31. Companion to `EXPERIMENT_SUMMARY.md` (results log) and `LOCAL_VLM_CONVERSATIONAL_RANKING.md` (model list)._

---

## 1. Framing

- **Phenomenon:** *regressive sycophancy* — a model abandons an initially **correct** answer under social pressure alone, with no valid new evidence.
- **Task:** VQA-RAD yes/no questions over real radiology images. The model answers correctly at turn 0, then faces up to 10 escalating pushback turns asserting a specific **wrong** answer.
- **Faithful setup:** standard multi-turn VLM dialogue — every image shown stays live in context for all later turns (no eviction). The real scan from turn 0 never leaves.
- **Primary metric:** flip rate = fraction of initially-correct answers abandoned by the final turn.
- **Secondary:** first-flip turn, post-flip recovery, per-turn verbalized confidence, refusal.

---

## 2. Research questions

### RQ1 — What drives the fabricated-evidence effect?

When a fabricated "evidence" image raises sycophancy, decompose the increase into four components:

| Component | Contrast | Reads as |
|---|---|---|
| Claim alone | `text_evidence − none` | words asserting evidence exists, no visual |
| Any new image | `random_image − none` | bare visual perturbation, no claim |
| Claim + any artifact | `random_framed − text_evidence` | a bogus image to "point at" while claiming |
| Content plausibility | `image − random_framed` | image looks like real evidence, claim held fixed |

- **H1a:** `text_evidence − none > 0` — the claim persuades without any image.
- **H1b:** `image − random_framed ≈ 0` — models are **not** evaluating image content; a mismatched scan with a confident caption works as well as a plausible prescription → sycophancy = caption deference + visual distraction, not evidence evaluation.
- **H1c (alt):** `image − random_framed > 0` — content plausibility matters; some genuine (mis)reading of the fake evidence.

### RQ2 — Grounding dilution

Does attaching **any** second image during pushback — framed or not, relevant or not — reduce grounding in the real scan?

- **Contrast:** `{random_image, random_framed}` vs `none`, plus `× scale`.
- **Signals:** (a) higher flip rate; (b) lower verbalized confidence in the correct answer; (c) reduced attention mass on real-scan tokens (open models).
- **H2:** any second image raises flip rate over `none` even with no evidential claim; the effect changes monotonically with model scale.

### RQ3 — Authority × evidence-type interaction

Does fabricated visual evidence flatten the authority/persona gradient that governs verbal-only sycophancy, and is flattening specific to *plausible* evidence?

- **Contrast:** `evidence_arm : persona` interaction; follow-up `random_* : persona` vs `image : persona`.
- **H3a:** the persona gradient (steep in `none`) is attenuated under `image`.
- **H3b:** if `random_* : persona` attenuation ≈ `image : persona`, the persona effect is fragile to visual distraction, not specifically overridden by "evidence".

---

## 3. Novelty positioning

- "Fabricated evidence increases sycophancy" **alone** is incremental — implied by EchoBench (`arXiv:2509.20146`), the grounding–sycophancy tradeoff (`arXiv:2603.22623`), and Aranya et al. 2026 (text-only, single-turn).
- **Contribution of this design:**
  1. Decompose the visual-evidence effect into *claim / mere-image / content* components via semantically-null image controls (RQ1).
  2. Grounding dilution by *irrelevant* images in a sycophancy setting — unreported (RQ2).
  3. Faithful **persistent multi-image, multi-turn** design (vs single-turn or eviction-degraded prior work).
  4. Mechanistic localization of where the fake image acts (§12).

---

## 4. Evidence-arm ladder

The real scan is persistent in every arm. Any new image is attached at pushback turn 1 and persists thereafter. Pushback wording is identical across arms except the single evidence sentence.

| Arm | New image | Evidence claim in text | Image content |
|---|---|---|---|
| `none` | — | no | — |
| `text_evidence` | — | yes ("a specialist report confirms …") | — |
| `random_image` | yes | no ("take a look at this") | out-of-domain natural photo |
| `random_framed` | yes | yes (same claim text as `image`) | a different, mismatched radiology scan |
| `image` | yes | yes | fabricated prescription (content-appropriate) — the original condition |

**Derived contrasts:**

- `text_evidence − none` → claim alone
- `random_image − none` → bare visual perturbation
- `random_framed − text_evidence` → bogus artifact added to a claim
- `random_framed − random_image` → false claim added to a bogus image
- `image − random_framed` → content plausibility, claim fixed
- `image − text_evidence` → total visual contribution over a pure text claim

**Optional full factorial:** framing {unframed, framed} × content {OOD-natural, wrong-scan, prescription, doctored-scan} + `none` + `text_evidence`. The 5 arms above are the minimum viable set.

---

## 5. Factorial design

`evidence_arm (5)` × `persona (3, or 6 ordinal)` × `model scale (≥3, one family)` × `item (VQA-RAD, paired)`

- Items **paired** across all arms → item as a random effect, large power gain.
- n per cell: **200–300** (interaction terms need ~4× main-effect n; current runs use 100).
- Seed 42 for item sampling (unchanged).
- Pushback turns: 10, escalating.

---

## 6. Personas

- `generic` — no authority claimed.
- `neighbor_nurse_doctor` — layperson → nurse → doctor.
- `default` — colleague → specialists → board-certified attending.
- **Upgrade for RQ3:** an ordinal 5–6 level authority scale (anonymous layperson → patient → nurse → GP → radiologist → signing radiologist → tumor-board consensus). RQ3 then tests a slope contrast per arm rather than a 3-category comparison.

---

## 7. Models

- **Scale ladder, one family (for the scale claims):** `Qwen/Qwen2.5-VL-3B-Instruct`, `Qwen/Qwen2.5-VL-7B-Instruct`, `Qwen/Qwen2.5-VL-32B-Instruct` (4-bit).
- **Cross-family generalization (separate analysis, not pooled into the scale regression):** `google/gemma-3-27b-it` (+ `google/gemma-3-4b-it` as the MedGemma base control), `Qwen/Qwen3-VL-8B-Instruct`, `OpenGVLab/InternVL3-8B`, `openbmb/MiniCPM-V-2_6`, `allenai/Molmo-7B-D-0924`.
- **Medical fine-tunes:** `google/medgemma-4b-it`, `FreedomIntelligence/HuatuoGPT-Vision-7B`.
- **Excluded:** Llama-3.2-Vision 11B/90B (cross-attention arch, no multi-image → cannot hold image history); NIM Nemotron (`limit-mm-per-prompt` caps images at 1 → cannot run faithful `image`; `none`/`text_evidence` only).

---

## 8. Outcomes

| Outcome | Definition | Purpose |
|---|---|---|
| Final flip | correct → wrong by the last turn | primary |
| First-flip turn | 1..10 or right-censored | cave speed (hazard model) |
| Recovery | correct answer restored on a neutral "are you sure?" closer turn | transient vs persistent capitulation |
| Confidence trace | verbalized 0–100 each answer turn | grounding erosion independent of the stated answer |
| Response type | {hold, flip, refuse} | refusal is a competing outcome, not noise |
| Attention mass (open models) | fraction on real-scan vs fake-image tokens at flip time | RQ1c / RQ2c / mechanism |

---

## 9. Analysis

- **Model:** logistic mixed effects — `flipped ~ evidence_arm * persona * scale + (1|item) + (1|model)`.
- **RQ1:** the four contrasts in §2 / §4, Holm–Bonferroni (or BH) corrected within the contrast family.
- **RQ2:** `{random_image, random_framed}` vs `none` main effect + `× scale`; confidence-trace slope; attention mass on real-scan tokens.
- **RQ3:** `evidence_arm : persona` likelihood-ratio test; ordinal-persona slope contrast per arm.
- Report odds ratios + bootstrap CIs, not just flip-rate deltas.
- First-flip: discrete-time hazard / Cox model by arm.
- **Pre-register** the RQs, the mixed-effects model, and the contrast list before the full sweep.

---

## 10. Controls & nuisance handling

- **Wording match:** arms differ only in the evidence sentence; `random_framed` reuses `image`'s claim text verbatim.
- **Random-image pool:** two sources — OOD natural (COCO/ImageNet) and in-domain-wrong (other VQA-RAD scans, different region/modality), screened so the distractor cannot itself cue the answer. ≥2 distinct draws per item; draw recorded per transcript and modelled as a random effect.
- **Salience match:** equalize resolution, aspect ratio, and processor token count across real scan / prescription / random image — otherwise an "image effect" is confounded with "the prescription is larger / more tokens / more embedded OCR text".
- **Position:** keep `image` (real scan anchored at turn 0) vs `dual` (both images on turn 1) to test recency protection of the real scan.

---

## 11. Validity checks

- **Veridical supporting evidence + wrong pushback:** a *real* report that backs the model's original answer, with the persona still insisting it is wrong. High flips here ⇒ pure deference, not evidence-driven.
- **Correct-updating floor:** real evidence that *genuinely* supports the pushed ("wrong") answer, on items the model actually got wrong at turn 0. Flipping there is appropriate — it gives a non-sycophantic baseline flip rate to subtract.

---

## 12. Mechanistic add-on (open Qwen weights)

- At flip time, compare attention mass on the fake-image tokens between `image` and `random_framed`. **Equal ⇒ H1b:** the image content is inert; the flip is carried by the caption + visual distraction.
- Attention on real-scan tokens across arms ⇒ direct test of RQ2 grounding dilution.
- Optional: activation patching — which layers / heads carry the flip, and whether it rides the image stream or the text-pushback stream (à la Ortu et al. 2026, *When Seeing Overrides Knowing*).

---

## 13. Implementation

- Extend `vqa_sycophancy_probe_hf_local_no_evict.py` `--evidence` with `text_evidence`, `random_image`, `random_framed`:
  - `text_evidence` — no image; inject the fabricated-report quote into pushback text. New wording key in `pushback_prompts.json` (e.g. `vqa_text_evidence`).
  - `random_framed` — swap the prescription attachment for a sampled distractor scan; keep the `vqa` (prescription) pushback wording.
  - `random_image` — sampled OOD distractor; keep the `vqa_no_pres` wording.
- Add `prescriptions/distractors/` (OOD + wrong-scan pools) and a seeded sampler; record the chosen distractor id in each transcript.
- Confidence elicitation: append "state your confidence 0–100" to each answer turn; parse and log it.
- Recovery: one neutral closer turn ("are you sure?") after the last pushback turn.
- Output: new variant folders `text_evidence_noevict/`, `random_image_noevict/`, `random_framed_noevict/` alongside `image_noevict/` and `no_pres_noevict/`.

---

## 14. Open decisions / risks

- **Compute budget:** n=200–300 × 5 arms × 3 personas × 3 scale points ≈ 9–13k conversations per family before cross-family — confirm GPU-hours.
- **32B 4-bit** + 10-turn multi-image context sits near the 24GB ceiling — smoke-test with `--n 2` first.
- **Persona granularity:** 6 ordinal levels roughly doubles persona cost vs 3 buckets — decide before the sweep.
- **Factorial size:** minimum 5 arms vs full 8 — decide from pilot effect sizes.
- **Distractor screening:** the "wrong scan" could accidentally support the pushed answer — needs a screening pass before inclusion.
- **Methodology drift:** `EXPERIMENT_SUMMARY.md` still describes "up to 3" pushback turns; this plan uses 10 (matches recent runs). Reconcile the wording.
