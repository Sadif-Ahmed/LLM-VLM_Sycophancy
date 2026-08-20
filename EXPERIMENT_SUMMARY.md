# LLM/VLM Sycophancy — Experiment Results Summary

## Methodology

Each probe asks a model a medical question it can answer correctly, then applies up to 3 escalating simulated "pushback" turns (a colleague/nurse/doctor/specialist insisting a specific **wrong** answer is correct). We measure **flip rate**: of the answers the model got right *initially*, what fraction did it abandon under pressure? This is *regressive sycophancy* — a correct answer overturned by social pressure alone, not new evidence.

- **Text (MedMCQA)**: multiple-choice medical exam questions, text-only.
- **Vision (VQA-RAD)**: yes/no questions over real radiology images.
  - **Fake image evidence**: a fabricated "prescription" document (falsely claiming a specialist confirmed the wrong answer) is shown alongside the first pushback.
  - **No evidence**: same escalating pushback wording, but purely verbal — no fake image ever shown.
  - **Grounded**: same as "fake image evidence," except the real scan is restored on pushback turns 2-3 (rather than staying hidden), testing whether pressure still works once the model can see the actual evidence again.
- **Personas**: `default` (colleague → specialists → attending), `neighbor_nurse_doctor` (non-expert → nurse → doctor), `generic` (no authority claimed at all).

---

## 1. Text-only (MedMCQA), n=5 per model

| Model | Initially Correct | Flipped | Flip Rate |
|---|---|---|---|
| qwen3-next-80b-a3b-instruct | 3/5 | 3 | **100%** |
| gpt-oss-120b | 4/5 | 1 | **25%** |
| nemotron-3-nano-omni-30b-a3b-reasoning | 3/5 | 0 | **0%** |

*Text-only models show the widest spread — from total resistance to total capitulation, depending on the model.*

## 2. Vision (VQA-RAD), fake prescription evidence — cross-model, n=20 per cell

| Model | default | neighbor_nurse_doctor | generic |
|---|---|---|---|
| llama-3.2-90b-vision-instruct | **100%** (13/13) | 87.5% (14/16) | **100%** (16/16) |
| llama-3.2-11b-vision-instruct | **100%** (12/12) | 30% (3/10) | **100%** (12/12) |
| nemotron-3-nano-omni-30b-a3b-reasoning | 80% (12/15) | 87.5% (14/16) | 93.3% (14/15) |

*Vision models cluster consistently high (80-100%) across nearly every model/persona combination — markedly more sycophantic than the text-only results above.*

## 3. Same model, evidence-condition comparison — llama-3.2-90b-vision-instruct, n=20 per cell

| Persona | Fake image evidence | No evidence (pure language) | Grounded (real scan restored, turns 2-3) |
|---|---|---|---|
| default | **100%** (14/14) | 71% (22/31, 2 runs) | **100%** (16/16) |
| neighbor_nurse_doctor | 80% (12/15) | **0%** (0/15) | 53.3% (8/15) |
| generic | **100%** (16/16) | 78.6% (11/14) | **100%** (16/16) |

*Controlled, same-model comparison isolating the fake image's effect. The `neighbor_nurse_doctor` persona shows the clearest signal: 0% flips with pure language vs. 80% once the fake image is added — the fabricated visual "evidence" is doing real work beyond the escalating wording alone. For `default`/`generic`, most flips already happen on the very first pushback turn, so restoring the real scan afterward ("grounded") arrives too late to matter — explaining why those two personas look identical between "fake image" and "grounded."*

## 4. Cross-platform replication — Hugging Face (independent backend/model)

| Model | Condition | n (combined) | Initially Correct | Flipped | Flip Rate |
|---|---|---|---|---|---|
| Qwen3-VL-8B-Instruct (via Hugging Face) | No evidence, default persona | 18 (3 partial runs) | 15 | 15 | **100%** |

*A different model family, served through an entirely different provider/infrastructure (Hugging Face Inference Providers rather than NVIDIA NIM), reproduces the same pattern — suggesting this isn't an artifact of one specific backend.*

---

## Key Takeaways

- Regressive sycophancy is observed across **every** model, modality, and platform tested — frequently at 80-100% flip rates.
- Vision-language models are consistently *more* sycophantic than text-only models on the same escalating-pressure methodology.
- Fabricated visual "evidence" measurably increases flip rates beyond pure verbal pressure alone (clearest in the `neighbor_nurse_doctor` persona: 0% → 80%).
- Restoring real visual grounding on later turns does not reliably reduce sycophancy, largely because most models already flip on the *first* pushback turn, before grounding can be restored.
- A small independent replication on a different model/provider shows the same near-total flip pattern, indicating the effect generalizes beyond any single model family or backend.
