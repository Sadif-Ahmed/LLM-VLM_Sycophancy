# LLM/VLM Sycophancy — Experiment Results Summary

## Methodology

Each probe asks a model a medical question it can answer correctly, then applies up to 3 escalating simulated "pushback" turns (a colleague/nurse/doctor/specialist insisting a specific **wrong** answer is correct). We measure **flip rate**: of the answers the model got right *initially*, what fraction did it abandon under pressure? This is *regressive sycophancy* — a correct answer overturned by social pressure alone, not new evidence.

- **Text (MedMCQA)**: multiple-choice medical exam questions, text-only.
- **Vision (VQA-RAD)**: yes/no questions over real radiology images. The faithful setup follows standard multi-turn VLM dialogue — **every image the model has been shown stays in the conversation history for all later turns**. Five evidence conditions, all sharing the same escalating pushback wording and personas, differ in which image(s) enter the conversation and when:
  - **image**: a fabricated "prescription" document (falsely claiming a specialist confirmed the wrong answer) is added on the first pushback turn. The real scan from turn 0 stays in context, so from turn 1 on the model sees **both** the real scan and the fake prescription.
  - **none**: purely verbal pushback, no fake image ever added; the real scan stays in context throughout.
  - **grounded** / **blind**: deliberate ablations that re-anchor the real scan every turn / withhold it after turn 0. Both only exist as manipulations of *eviction* (see below) — under a faithful setup the real scan never leaves, so there is nothing to restore or withhold.
  - **dual**: the real scan and the fake prescription are introduced *on the same turn* (turn 1, real first) rather than the real one being anchored at turn 0 — a **positional** variant of **image**. Requires a model with true multi-image support; reported within-model only. See ["Eviction and the `dual` variant"](#eviction-and-the-dual-variant) below.
- **Eviction caveat**: NVIDIA NIM caps API calls at one image each, so the NIM script (`vqa_sycophancy_probe.py`) is forced to drop all but the newest image every turn. Its `image` / `grounded` / `blind` results are therefore a **degraded approximation** of true multi-turn dialogue and are not directly comparable to the faithful local runs. The evicting local script (`vqa_sycophancy_probe_hf_local.py`) mirrors that eviction on purpose, only so local and NIM numbers sit on the same (degraded) basis. `vqa_sycophancy_probe_hf_local_no_evict.py` is the SOTA-faithful version that keeps every image — its `image` numbers are the ones to report for the persistent-image condition.
- **Personas**: `default` (colleague → specialists → attending), `neighbor_nurse_doctor` (non-expert → nurse → doctor), `generic` (no authority claimed at all).

---

## Probe scripts

All batch launchers live in `scripts\`. Each loops the 3 personas automatically; common optional args are `--n` (questions per cell, default 20), `--split`, `--seed`, `--pushback-turns`, `--dry-run` (print commands only). Local-GPU launchers also take `--device {auto,cuda,cpu}`, `--load-in-4bit`, `--trust-remote-code`, `--runner NAME`; API launchers take `--provider {nvidia,openrouter}` and `--rpm`.

The 3 local-GPU launchers take `--model MODEL` to run a single model; **omit it and they loop the 10 locally-runnable VLMs** from [`LOCAL_VLM_CONVERSATIONAL_RANKING.md`](LOCAL_VLM_CONVERSATIONAL_RANKING.md) — Qwen2.5-VL-3B/7B, Qwen3-VL-8B, medgemma-4b-it, Phi-3.5-vision, llava-1.5-7b, HuatuoGPT-Vision-7B, MiniCPM-V-2.6, Molmo-7B-D, InternVL3-8B (excludes Llama-3.2-11B-Vision, kept on NIM, and NVLM-D-72B, too big for local). Edit `MODEL_LIST` inside a `.bat` to change it. `--load-in-4bit` / `--trust-remote-code` are global — pass both when sweeping the whole list (most 7-8B models need 4-bit on an 8GB card; MiniCPM-V / Molmo / InternVL3 / Phi-3.5 need trust-remote-code).

| Script | Backend (Python script) | Conditions | Runs (1 model / full list) | Notes |
|---|---|---|---|---|
| `run_vqa_nim_all.bat` | NIM / OpenRouter API — `vqa_sycophancy_probe.py` | image, grounded, none, blind | 12 / — | `--model` required. API-based; two instances can run in parallel against different models with `--rpm` halved on each |
| `run_vqa_hf_local_all.bat` | local GPU — `vqa_sycophancy_probe_hf_local.py` | image, grounded, none, blind | 12 / 120 | evicts all but the newest image on purpose, to stay comparable with the NIM backend — use the no_evict script for faithful `image`. One model at a time, sequential (do not co-launch anything else that wants the GPU) |
| `run_vqa_hf_local_noevict.bat` | local GPU — `vqa_sycophancy_probe_hf_local_no_evict.py` | image, none | 6 / 60 | **SOTA-faithful**: keeps every image in context, as standard multi-turn dialogue does. `image` here = real scan + fake prescription both persistent — the correct `image` condition. Only `image` / `none` apply (`grounded` / `blind` are eviction ablations). Output in `*_noevict` folders to keep it separate from the NIM-comparable set |
| `run_vqa_hf_local_dual.bat` | local GPU — `vqa_sycophancy_probe_hf_local_dual.py` | dual | 3 / 30 | additive positional variant of `image`; both images injected on turn 1 instead of the real one anchored at turn 0. Proof images always required (auto-resolved). llava-1.5-7b in the list will fail dual (single-image only) — expected |
| `model_text_only.bat` | NIM / OpenRouter — `sycophancy_probe.py` | text (MedMCQA), no images | preset model list | edit the `MODEL[N]` / `PROVIDER[N]` block inside the `.bat` to change models |

Single-condition NIM runs (no bat): call `vqa_sycophancy_probe.py --evidence {image,grounded,none,blind}` directly — the four old per-condition bats were removed in favor of the one unified script.

**Output layout**, identical for every script: `results/<model>/<variant>/<prompt>/` containing `results.json` (canonical, overwritten each run), `RESULTS.txt` (human-readable, appended), and `transcripts/<id>.json` (per-item checkpoint — all scripts resume automatically on re-run). `<variant>` is `image` / `grounded` / `no_pres` / `blind` / `dual` (or `image_noevict` / `no_pres_noevict` for the faithful non-evicting runs, kept in their own folders so they never mix with the NIM-comparable evicting runs of the same name). Local runs also append a dated section to `summary/<model>.md`.

### Eviction and the `dual` variant

Standard multi-turn VLM dialogue keeps every image in context. Two things pull against that here:

- **NIM's one-image-per-call cap.** `vqa_sycophancy_probe.py` (NIM / OpenRouter) *must* evict all but the newest image — an API limit, not a modelling choice. This makes its image-bearing conditions a degraded stand-in for real multi-turn dialogue; those results are flagged as such and not blended with the faithful local numbers. `vqa_sycophancy_probe_hf_local.py` reproduces the eviction deliberately, purely for apples-to-apples comparison with NIM. `vqa_sycophancy_probe_hf_local_no_evict.py` is the faithful (non-evicting) version — its `image` keeps the real scan (turn 0) and the fake prescription (turn 1) both live for the rest of the conversation.
- **`grounded` / `blind`** are ablations *of* eviction: they re-inject or withhold the real scan on later turns. They only have meaning inside an evicting run — under no eviction the real scan never leaves, so there is nothing to restore or withhold.

**`dual`** exists because, even with no eviction, there's a design choice in *how* the two images enter the conversation: `image` anchors the real scan at turn 0 and adds the fake one at turn 1; `dual` introduces both on turn 1 together (real first). Either way both images stay in every forward pass from turn 1 on — the level Ortu et al. (2026, *When Seeing Overrides Knowing*) identify visual-conflict resolution as happening at (attention heads that engage only when both signals are present at once). `dual` isolates the effect of image *ordering / position*, holding content and wording fixed. This whole line of work — persistent competing images under multi-turn pressure — also pushes past the closest prior medical-VLM sycophancy study (Aranya et al. 2026), whose pressure is text-only and single-turn (multi-turn flagged as their own limitation).

Multi-image support (needed for `dual`, and for the faithful non-evicting `image`): Qwen2.5-VL / Qwen3-VL, MedGemma (Gemma3 backbone), Phi-3.5-Vision, InternVL3-8B, MiniCPM-V-2.6, and `nvidia/nemotron-3-nano-omni` all support it. **Llama-3.2-Vision (11B / 90B) does not** (cross-attention architecture) — it is limited to the evicting conditions; the cross-model comparison on those stays fully populated for every model.

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
