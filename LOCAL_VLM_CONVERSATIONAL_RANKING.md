# Local VLM Selection — Conversational Prowess vs. VRAM

Re-evaluation of the [LOCAL_VLM_COMPATIBILITY.md](LOCAL_VLM_COMPATIBILITY.md)
candidate list against a different axis: how well each model's **text
backbone** handles sustained, multi-turn instruction-following — since a
10-turn escalating-pushback sycophancy probe stresses conversational
coherence far more than it stresses raw vision-benchmark accuracy. Ranked
ascending by estimated VRAM (GGUF Q4_K_M quantization) for a target GPU
budget of **8GB** (RTX 3060 Ti).

## Ranked by VRAM (models worth running)

HF Hub id is the `--model` value — copy it straight into any
`vqa_sycophancy_probe_hf_local*.py` / `run_vqa_hf_local_*.bat` call.

| `--model` (HF Hub id) | Backbone | Conversational fit | Run flags (8GB card) | Est. VRAM (Q4_K_M) |
|---|---|---|---|---|
| `Qwen/Qwen2.5-VL-3B-Instruct` | Qwen2.5-3B | Strong — Qwen's chat tuning is consistently top-tier at this size | _(none — fits in bf16)_ | ~2–2.5GB |
| `google/medgemma-4b-it` | Gemma3-4B | Good backbone, but ⚠️ narrowly fine-tuned on clinical Q&A — may not handle adversarial social-pressure dialogue naturally, since that's outside its fine-tuning distribution | `--load-in-4bit` | ~3–3.5GB |
| `microsoft/Phi-3.5-vision-instruct` | Phi-3.5 | Decent reasoning, but terser/less "chatty" by design | `--load-in-4bit --trust-remote-code` | ~3.5–4GB |
| `llava-hf/llava-1.5-7b-hf` | Vicuna (Llama-2 era) | Weak — dated backbone, plus single-image cap breaks the `image` / `grounded` variants (only `none` runs) | `--load-in-4bit` | ~4.5–5GB |
| `Qwen/Qwen2.5-VL-7B-Instruct` | Qwen2.5-7B | Strong, same family as 3B — best chat quality in the 7B class | `--load-in-4bit` | ~5.5–6.5GB |
| `Qwen/Qwen3-VL-8B-Instruct` | Qwen3-8B | Strong, newest Qwen chat tuning | `--load-in-4bit` | ~6–7GB |
| `FreedomIntelligence/HuatuoGPT-Vision-7B` | Qwen2.5-VL-7B or LLaMA-3-8B (verify which per checkpoint) | ⚠️ Unverified — medical fine-tune, likely inherits its base's chat quality if it's the Qwen2.5-VL backbone variant, but check the HF repo's `config.json` architecture class before assuming it loads via `AutoModelForImageTextToText` unmodified | `--load-in-4bit --trust-remote-code` | ~5.5–7GB (same class as its 7B/8B base) |
| `openbmb/MiniCPM-V-2_6` | Qwen2-7B | Strong — inherits Qwen's chat quality | `--load-in-4bit --trust-remote-code` | ~6–7GB |
| `allenai/Molmo-7B-D-0924` | Qwen2-7B | Strong, same reason | `--load-in-4bit --trust-remote-code` | ~6–7GB |
| `OpenGVLab/InternVL3-8B` | Qwen2.5-7B (most sizes) | Strong, same reason | `--load-in-4bit --trust-remote-code` | ~6–7GB |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | Nemotron 30B MoE (~3B active) | Strong; multi-image OK — see caveats | 4-bit only (30B won't fit bf16 in 24GB); `--trust-remote-code`, omni model — local load via the probe is **unverified**, results so far are NIM | ~15–16GB (4-bit) |
| `nvidia/NVLM-D-72B` | Qwen2-72B-Instruct | Best-in-class chat quality | **impossible locally** (~40GB+ even at Q4) | — |

## Next tier — >8B, needs a 24GB card (run after the 10-model list)

All support persistent multi-image. The dense 27–32B entries need `--load-in-4bit`
even on a 4090 (won't fit bf16 in 24GB); the small ones don't.

| `--model` (HF Hub id) | Backbone | Why run it | VRAM (4-bit) |
|---|---|---|---|
| `Qwen/Qwen2.5-VL-32B-Instruct` | Qwen2.5-32B | **Primary pick.** Completes a 3-point scaling curve (3B → 7B → 32B) in one family, same loader / chat template — answers whether sycophancy keeps dropping with scale or plateaus after 7B. Top open model in its class on OpenVLM / MMMU. No trust-remote-code. `--load-in-4bit`. | ~19–21GB |
| `google/gemma-3-27b-it` | Gemma3-27B | Different lineage from Qwen; native multi-image; strong benches. Run `google/gemma-3-4b-it` (plain base of MedGemma) alongside as a control — separates "medical fine-tune → more sycophantic" from Gemma3 base behavior. `--load-in-4bit` (27B); the 4B fits bf16. | ~17–19GB (27B) |
| `moonshotai/Kimi-VL-A3B-Thinking-2506` | Kimi-VL MoE (~3B active) | Only "thinking" VLM in the set — tests whether visible reasoning traces make it hold or fold under escalating pushback. Cheap to run. `--trust-remote-code`; higher integration risk (custom modeling code). | ~6–9GB |

Verify each with `--n 2` before a full sweep — 32B 4-bit + 10-turn multi-image
context sits close to the 24GB ceiling.

```bat
scripts\run_vqa_hf_local_noevict.bat --model Qwen/Qwen2.5-VL-32B-Instruct --n 100 --load-in-4bit
scripts\run_vqa_hf_local_noevict.bat --model google/gemma-3-27b-it --n 100 --load-in-4bit
scripts\run_vqa_hf_local_noevict.bat --model google/gemma-3-4b-it --n 100
scripts\run_vqa_hf_local_noevict.bat --model moonshotai/Kimi-VL-A3B-Thinking-2506 --n 100 --trust-remote-code
```

## Excluded — no multi-image support (can't hold image history)

The faithful (no-evict) design keeps every shown image live for all later turns.
These models can't, so they're out regardless of chat quality or VRAM:

- `meta-llama/Llama-3.2-11B-Vision-Instruct`, `meta-llama/Llama-3.2-90B-Vision-Instruct` — cross-attention vision architecture, single-image only. Conversationally very strong (heaviest RLHF of the lot), but structurally incompatible: no persistent image history, so only the retired evicting conditions ever applied. Prior results are NIM-only.

## Excluded outright — conversational prowess is the disqualifier, not size

- `moondream2` — not trained for open dialogue at all (captioning/pointing/query only)
- `PaliGemma2-*` — not chat-tuned, no instruction-following
- `BLIP-2-OPT-2.7B` — 2023-era, not chat-tuned
- `LLaVA-v1.6-7B`, `llava-med-v1.5-mistral-7b` — same dated Vicuna/old-LLaVA lineage as 1.5

## Practical pick order (RTX 3060 Ti, 8GB VRAM)

1. **`Qwen/Qwen2.5-VL-3B-Instruct`** first — cheap, validates the local-hosting pipeline before committing GPU-hours
2. **`Qwen/Qwen2.5-VL-7B-Instruct`** or **`Qwen/Qwen3-VL-8B-Instruct`** next — best conversational quality that still fits, tight but workable
3. `google/medgemma-4b-it` only if the medical-specificity is worth trading off against its clinical-narrowness caveat above
4. `FreedomIntelligence/HuatuoGPT-Vision-7B` — second medical-fine-tune data point alongside medgemma, once its architecture class is confirmed compatible
5. **After the list (24GB card): `Qwen/Qwen2.5-VL-32B-Instruct`** — extends the 3B/7B scaling line; then `google/gemma-3-27b-it` (+ `gemma-3-4b-it` control) and `moonshotai/Kimi-VL-A3B-Thinking-2506` (reasoning-trace axis). See "Next tier" above.

## Copy-paste — faithful (no-evict) sweep, n=100

Each line = `image` + `none` × 3 personas = 6 runs. Proof images auto-resolved by the launcher.

```bat
scripts\run_vqa_hf_local_noevict.bat --model Qwen/Qwen2.5-VL-3B-Instruct --n 100
scripts\run_vqa_hf_local_noevict.bat --model Qwen/Qwen2.5-VL-7B-Instruct --n 100 --load-in-4bit
scripts\run_vqa_hf_local_noevict.bat --model Qwen/Qwen3-VL-8B-Instruct --n 100 --load-in-4bit
scripts\run_vqa_hf_local_noevict.bat --model google/medgemma-4b-it --n 100 --load-in-4bit
scripts\run_vqa_hf_local_noevict.bat --model microsoft/Phi-3.5-vision-instruct --n 100 --load-in-4bit --trust-remote-code
scripts\run_vqa_hf_local_noevict.bat --model openbmb/MiniCPM-V-2_6 --n 100 --load-in-4bit --trust-remote-code
scripts\run_vqa_hf_local_noevict.bat --model allenai/Molmo-7B-D-0924 --n 100 --load-in-4bit --trust-remote-code
scripts\run_vqa_hf_local_noevict.bat --model OpenGVLab/InternVL3-8B --n 100 --load-in-4bit --trust-remote-code
scripts\run_vqa_hf_local_noevict.bat --model FreedomIntelligence/HuatuoGPT-Vision-7B --n 100 --load-in-4bit --trust-remote-code
```

`llava-hf/llava-1.5-7b-hf` is single-image — noevict `image` will fail, run `none` only:

```bat
.venv\Scripts\python.exe vqa_sycophancy_probe_hf_local_no_evict.py --model llava-hf/llava-1.5-7b-hf --evidence none --n 100 --prompt-set default --load-in-4bit
```

Omit `--model` from the launcher to sweep the whole 10-model list (`--load-in-4bit --trust-remote-code` become global — pass both).

### On a 24GB card (RTX 4090) — no 4-bit

Every model above is ≤8B and fits in bf16 on 24GB (~6GB for 3B, ~16GB for 7–8B). Drop `--load-in-4bit`, keep `--trust-remote-code` (architecture requirement, not VRAM). Matches the dtype the existing `*_noevict` results were produced at.

```bat
scripts\run_vqa_hf_local_noevict.bat --model Qwen/Qwen2.5-VL-3B-Instruct --n 100
scripts\run_vqa_hf_local_noevict.bat --model Qwen/Qwen2.5-VL-7B-Instruct --n 100
scripts\run_vqa_hf_local_noevict.bat --model Qwen/Qwen3-VL-8B-Instruct --n 100
scripts\run_vqa_hf_local_noevict.bat --model google/medgemma-4b-it --n 100
scripts\run_vqa_hf_local_noevict.bat --model microsoft/Phi-3.5-vision-instruct --n 100 --trust-remote-code
scripts\run_vqa_hf_local_noevict.bat --model openbmb/MiniCPM-V-2_6 --n 100 --trust-remote-code
scripts\run_vqa_hf_local_noevict.bat --model allenai/Molmo-7B-D-0924 --n 100 --trust-remote-code
scripts\run_vqa_hf_local_noevict.bat --model OpenGVLab/InternVL3-8B --n 100 --trust-remote-code
scripts\run_vqa_hf_local_noevict.bat --model FreedomIntelligence/HuatuoGPT-Vision-7B --n 100 --trust-remote-code
```
