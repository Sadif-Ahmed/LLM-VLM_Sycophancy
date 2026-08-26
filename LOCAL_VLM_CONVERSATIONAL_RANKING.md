# Local VLM Selection — Conversational Prowess vs. VRAM

Re-evaluation of the [LOCAL_VLM_COMPATIBILITY.md](LOCAL_VLM_COMPATIBILITY.md)
candidate list against a different axis: how well each model's **text
backbone** handles sustained, multi-turn instruction-following — since a
10-turn escalating-pushback sycophancy probe stresses conversational
coherence far more than it stresses raw vision-benchmark accuracy. Ranked
ascending by estimated VRAM (GGUF Q4_K_M quantization) for a target GPU
budget of **8GB** (RTX 3060 Ti).

## Ranked by VRAM (models worth running)

| Model | Backbone | Conversational fit | Est. VRAM (Q4_K_M) |
|---|---|---|---|
| `Qwen2.5-VL-3B-Instruct` | Qwen2.5-3B | Strong — Qwen's chat tuning is consistently top-tier at this size | ~2–2.5GB |
| `medgemma-4b-it` | Gemma3-4B | Good backbone, but ⚠️ narrowly fine-tuned on clinical Q&A — may not handle adversarial social-pressure dialogue naturally, since that's outside its fine-tuning distribution | ~3–3.5GB |
| `Phi-3.5-Vision` (4.2B) | Phi-3.5 | Decent reasoning, but terser/less "chatty" by design | ~3.5–4GB |
| `LLaVA-1.5-7b-hf` | Vicuna (Llama-2 era) | Weak — dated backbone, plus single-image cap breaks the grounded variant | ~4.5–5GB |
| `Qwen2.5-VL-7B-Instruct` | Qwen2.5-7B | Strong, same family as 3B — best chat quality in the 7B class | ~5.5–6.5GB |
| `Qwen3-VL-8B-Instruct` | Qwen3-8B | Strong, newest Qwen chat tuning | ~6–7GB |
| `HuatuoGPT-Vision-7B` | Qwen2.5-VL-7B or LLaMA-3-8B (verify which per checkpoint) | ⚠️ Unverified — medical fine-tune, likely inherits its base's chat quality if it's the Qwen2.5-VL backbone variant, but check the HF repo's `config.json` architecture class before assuming it loads via `AutoModelForImageTextToText` unmodified | ~5.5–7GB (same class as its 7B/8B base) |
| `MiniCPM-V-2_6` | Qwen2-7B | Strong — inherits Qwen's chat quality | ~6–7GB |
| `Molmo-7B-D-0924` | Qwen2-7B | Strong, same reason | ~6–7GB |
| `InternVL3-8B` | Qwen2.5-7B (most sizes) | Strong, same reason | ~6–7GB |
| `Llama-3.2-11B-Vision-Instruct` | Llama-3.1-8B | Very strong — heaviest RLHF of the lot, most natural chat feel | ~8–9GB — **doesn't fit 8GB card**, keep on NIM API |
| `NVLM-D-72B` | Qwen2-72B-Instruct | Best-in-class chat quality | ~40GB+ even at Q4 — **impossible locally** |

## Excluded outright — conversational prowess is the disqualifier, not size

- `moondream2` — not trained for open dialogue at all (captioning/pointing/query only)
- `PaliGemma2-*` — not chat-tuned, no instruction-following
- `BLIP-2-OPT-2.7B` — 2023-era, not chat-tuned
- `LLaVA-v1.6-7B`, `llava-med-v1.5-mistral-7b` — same dated Vicuna/old-LLaVA lineage as 1.5

## Practical pick order (RTX 3060 Ti, 8GB VRAM)

1. **`Qwen2.5-VL-3B-Instruct`** first — cheap, validates the local-hosting pipeline before committing GPU-hours
2. **`Qwen2.5-VL-7B-Instruct`** or **`Qwen3-VL-8B-Instruct`** next — best conversational quality that still fits, tight but workable
3. `medgemma-4b-it` only if the medical-specificity is worth trading off against its clinical-narrowness caveat above
4. `HuatuoGPT-Vision-7B` — second medical-fine-tune data point alongside medgemma, once its architecture class is confirmed compatible
