# Fix 2 — Simultaneous Dual-Image Condition (`dual`)

**Status: planned, not implemented.** Fix 1 (`blind`) is done — see
`vqa_sycophancy_probe_blind.py` / `run_vqa_blind.bat` and the `blind`
`--evidence` value in `vqa_sycophancy_probe_hf_local.py`. This document
covers Fix 2 only.

## Reasoning behind the change

The whole probe rests on a claim: multi-turn escalating pressure plus a fake
counter-image, tested across models, is a genuine methodological extension
of the sycophancy literature rather than a re-skin of existing benchmarks.
`image`/`grounded` already support that claim reasonably well, but they
share one weakness that undercuts it slightly — because the real image is
always lost the instant the fake one appears, nothing in the current design
can distinguish "the model capitulated because a fake image out-competed the
real one" from "the model capitulated because it lost visual access to the
answer and was left reasoning from memory under repeated verbal pressure."
`blind` isolates the second effect. `dual` is what isolates the first one
cleanly, and it's also the piece that pushes the design past merely
extending Aranya et al. (2026) — the closest prior medical-VLM sycophancy
work — into territory that work doesn't touch at all: Aranya et al.'s
pressure is confirmed purely textual and single-turn, with the authors
naming multi-turn pressure as their own acknowledged limitation, but neither
their design nor any other medical-VLM sycophancy paper found puts a real
and fabricated image in front of the model at the same time. Ortu et al.
(2026) give a mechanistic reason to expect this matters: visual-conflict
resolution in VLMs is mediated by a small set of attention heads that
attend far more heavily to image tokens than text when a conflict is live,
and that competition only happens when both signals are actually present in
the same forward pass — which sequential turns, however cleverly ordered,
never produce. Without `dual`, the probe can show that fake evidence
*correlates* with higher flip rates; with it, the probe can speak to
whether a model's stated answer holds up when the real and fake evidence
are literally competing for the same attention weights, which is a
meaningfully stronger and more mechanistically grounded claim.

## What this fixes

`image` confounds two manipulations on the same turn: the real image is lost
*and* a fake counter-image is introduced, at once. `grounded` only partially
disentangles this (recovery from turn 2 on). Fix 2 shows the real and fake
images **simultaneously on turn 1** — the one condition that actually puts
both signals in competition within the same forward pass, which is what
Ortu et al. (2026, *When Seeing Overrides Knowing*) identify as the level
visual-conflict resolution actually happens at (dedicated attention heads
attending far more to image tokens than text when resolving a conflict).
See the earlier literature justification for Aranya et al. (2026) confirming
the closest prior medical-VLM sycophancy work never tests this — text-only,
single-turn pressure, explicitly flagged by its own authors as a limitation.

Local-only. NIM's Llama-3.2-Vision models cannot take it regardless of
backend (cross-attention architecture, unreliable/unsupported beyond one
image) — this is a model-family limitation, not an infrastructure one, so it
doesn't invalidate the 4-condition (`no_pres`/`blind`/`image`/`grounded`)
cross-model comparison, which stays fully populated for every model
including Llama-3.2-Vision. `dual` results are reported separately,
within-model only, never blended into that main table.

## Model support

| Model | Multi-image support | Confidence |
|---|---|---|
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` (NIM, already tested) | ✅ yes — "multiple image reasoning" explicitly listed | High |
| `Qwen/Qwen2.5-VL-7B-Instruct` (local, already tested) | ✅ yes | High |
| `Qwen/Qwen3-VL-8B-Instruct` (local, already tested) | ✅ yes — native interleaved multi-image, up to 256K context | High |
| `google/medgemma-4b-it` (local, already tested) | ✅ yes — Gemma3 4B+ backbone | High |
| `Qwen2.5-VL-3B-Instruct` | ✅ yes, same family | High |
| `Phi-3.5-Vision` | ✅ yes — explicitly designed for multi-image, tokens concatenated | High |
| `MiniCPM-V-2_6` | ✅ yes — multi-image is a headline 2.6 feature (Mantis-Eval/BLINK) | High |
| `InternVL3-8B` | ✅ yes — multi-image/video is a core capability | High |
| `HuatuoGPT-Vision-7B` | ⚠️ depends on checkpoint — Qwen2.5-VL-backbone variant inherits yes, LLaMA-3-8B variant unconfirmed | Verify per checkpoint before use |
| `Molmo-7B-D-0924` | ⚠️ unconfirmed — no explicit multi-image documentation found | Verify individually |
| `meta/llama-3.2-11b-vision-instruct` (NIM, already tested) | ❌ no — cross-attention architecture | High |
| `meta/llama-3.2-90b-vision-instruct` (NIM, already tested) | ❌ same architecture | High |
| `LLaVA-1.5-7b-hf`, `LLaVA-v1.6-7B`, `llava-med-v1.5-mistral-7b` | ❌ no — single-image-per-conversation | High |
| `moondream2`, `PaliGemma2-*`, `BLIP-2-OPT-2.7B` | ❌ no — already excluded on conversational-fit grounds anyway | Moot |

**Note on nemotron-3-nano-omni:** hosted via NIM, but the multi-image
limitation for `dual` is architectural (Llama-3.2-Vision specifically), not
"NIM can't do it" — nemotron supports multiple images, so `dual` should work
for it via NIM too, unlike the Llama-3.2-Vision models. Worth confirming
NIM's API itself doesn't impose its own hard 1-image-per-call cap
independent of model architecture before assuming this works end-to-end.

Of the 6 already-tested models: **4 support `dual`** (nemotron-omni,
Qwen2.5-VL-7B, Qwen3-VL-8B, medgemma), **2 don't** (both Llama-3.2-Vision
sizes).

## Design decisions

1. **Silent attachment, no wording change.** Turn 1's pushback text stays
   byte-identical to what `image`/`grounded` already use ("here's a
   prescription confirming {wrong}..."). The real image rides along in the
   same message without the text acknowledging a second image. Rewriting
   the text to narrate two images ("here's the prescription, and for
   reference the original scan again...") would confound wording with image
   count — exactly the mistake `blind` was built to avoid repeating.

2. **Image order: real first, then fake.** Real image was established in
   turn 0, so it goes first (continuity); fake is the newly-introduced one,
   second. Flagged as a real experimenter choice — `[real, fake]` vs.
   `[fake, real]` is itself a legitimate future ablation, out of scope here.

3. **Turns 2–10 mirror `image`, not `grounded`.** Both images shown once on
   turn 1, nothing shown turns 2–10. This makes `image` vs. `dual` a clean
   single-variable comparison (1 vs. 2 images on turn 1, everything else
   identical). A "dual-then-recover" variant paralleling `grounded` is a
   sensible follow-up, but adding it now would mean shipping two new
   conditions at once instead of one clean one.

## Implementation plan

Scope: `vqa_sycophancy_probe_hf_local.py` only. No changes needed to
`_to_hf_messages()`/`call_local()` — they already convert every
`image_url` part in a message into its own `{"type":"image"}` placeholder
plus a flat-list entry, so multiple images in one message already flow
through to `apply_chat_template()` correctly once the message itself
carries two `image_url` parts.

Required changes:

- **`image_for_pushback_turn()` return type: `str | None` → `list[str]`.**
  Empty list = text-only (turns 2–10 for `dual`, and every non-image turn
  in `none`/`blind`), one-item list = today's single-image behavior
  (`image`/`grounded`), two-item list = `dual`'s turn 1 only.
- **Message-building loop in `run_probe()`** currently does one
  `if turn_img_b64 is not None: attach one image_url part`. Needs to become
  a loop appending one `image_url` part per image in the returned list, in
  order.
- **`--evidence` choices**: add `"dual"`.
- **`variant` mapping**: add `"dual": "dual"`.
- **Proof-image requirement check**: extend the `("image", "grounded")`
  tuple to include `"dual"` (needs `--proof-yes-image`/`--proof-no-image`
  same as the other two).
- **`load_prompt_sets()` domain**: `dual` uses the same `"vqa"` domain as
  `image`/`grounded` (prescription-referencing wording) — no change needed
  there beyond making sure `dual` isn't accidentally routed to
  `vqa_no_pres`.
- **`_selftest()`**: add assertions for the new list-returning
  `image_for_pushback_turn` signature across all four existing evidence
  values plus `dual`, since the return-type change affects every caller,
  not just the new mode.

Not touching the NIM scripts (`vqa_sycophancy_probe*.py`) — `dual` doesn't
apply to Llama-3.2-Vision, and nemotron-omni would need its own dedicated
NIM-side script if this gets extended there later; not planned yet.

## Open before implementing

The two design decisions above (silent attachment, real-then-fake order,
mirror-`image` turn structure) are locked in as the methodologically
tighter choice, but they're calls the user should explicitly confirm before
code gets written, not defaults assumed on their behalf.
