# Local VLM Hosting Compatibility

Candidate models from the (now-removed) `local_vlms.txt` research list, checked
against three local self-hosting servers that can expose an OpenAI-compatible
`/v1/chat/completions` endpoint — the same interface `conversation_sim.py`'s
`call_llm()` already speaks to NVIDIA NIM / OpenRouter / HF Inference
Providers. Any of the three would plug in by adding one entry to
`conversation_sim.py`'s `PROVIDERS` dict (same pattern
`vqa_sycophancy_probe_hf.py` used for the `huggingface` provider), e.g.:

```python
"local": {"base_url": "http://localhost:8000/v1", "env_var": "LOCAL_API_KEY", "default_rpm": 0}
```

## Servers checked

- **vLLM** — `vllm serve <model>`. Broadest coverage of the three; its
  supported-architectures list is close to a superset of the whole
  `local_vlms.txt` file, including models nothing else here could serve
  (MiniCPM-V's custom `.chat()` method, InternVL's custom class, even
  NVLM-D-72B natively).
- **Ollama** — curated model library, OpenAI-compatible endpoint. Narrower,
  but has some pleasant surprises (`medgemma`, `moondream` are both in the
  library).
- **llama.cpp server** (`libmtmd`) — GGUF + mmproj. Strong on the newer
  Qwen-VL/InternVL/Gemma lines, weak on Mllama (Llama-3.2-Vision's
  cross-attention architecture) and hasn't picked up several niche ones.

## Compatibility matrix

| Model | vLLM | Ollama | llama.cpp |
|---|---|---|---|
| Qwen2.5-VL-7B-Instruct | ✅ native | ⚠️ Qwen-VL family present, exact 2.5-7B tag unconfirmed | ✅ explicit |
| Qwen3-VL-8B-Instruct | ✅ native | ✅ `qwen3-vl` | ✅ explicit |
| llava-hf/llava-1.5-7b-hf | ✅ native | ✅ `llava` | ✅ explicit |
| llava-hf/llava-onevision-qwen2-7b-ov-hf | ✅ native | ❌ not in library | ⚠️ not confirmed |
| OpenGVLab/InternVL2_5-8B / InternVL3-8B | ✅ native (`InternVLChatModel`, 2.5 + 3.0) | ❌ not found | ✅ explicit (1B–14B range) |
| openbmb/MiniCPM-V-2_6 | ✅ native | ✅ (`minicpm-v4.5`/`4.6` — 2.6 itself superseded) | ✅ (needs newer checkpoint format) |
| meta-llama/Llama-3.2-11B-Vision-Instruct | ✅ native | ✅ `llama3.2-vision` | ⚠️ Mllama cross-attention arch historically weak |
| allenai/Molmo-7B-D-0924 | ⚠️ vLLM lists Molmo2 class; this older checkpoint unconfirmed | ❌ | ❌ |
| nvidia/NVLM-D-72B | ✅ native (`NVLM_D_Model`) | ❌ | ❌ |
| google/medgemma-4b-it / medgemma-27b-it | ✅ native (Gemma3 class) | ✅ `medgemma`/`medgemma1.5` | ✅ (Gemma 3 family) |
| vikhyatk/moondream2 | ⚠️ vLLM lists Moondream3 class; v2 unconfirmed | ✅ `moondream` | ✅ explicit |
| google/paligemma2-3b-pt-448 | ✅ loads, ⚠️ not chat-tuned regardless of host | ❌ | ❌ |
| HuggingFaceM4/SmolVLM2-2.2B-Instruct | ✅ native | ❌ not confirmed | ✅ explicit |
| microsoft/llava-med-v1.5-mistral-7b | ⚠️ matches LLaVA-1.5 class but original repo isn't in "-hf" format — likely needs conversion | ❌ | ⚠️ same caveat |
| Phi-3.5-Vision | ✅ native (`Phi3VForCausalLM`) | ❌ not found | ❌ not confirmed |
| Idefics2-8B | ⚠️ vLLM confirms Idefics3, Idefics2 unconfirmed | ❌ | ❌ |
| LFM-2-VL-1B / LFM-2-VL-8B | ✅ native (`Lfm2VlForConditionalGeneration`) | ❌ | ⚠️ unconfirmed (only LFM2-Audio found) |
| Qwen2-VL-2B, Qwen2.5-VL-3B | ✅ native | ⚠️ unconfirmed exact tags | ✅ explicit |
| BLIP-2-OPT-2.7B | ✅ loads, ⚠️ not chat-tuned | ❌ | ❌ |
| LLaVA-v1.6-7B | ✅ native (LLaVA-NeXT) | ✅ | ✅ explicit |
| PaliGemma2-10B | ✅ loads, ⚠️ not chat-tuned | ❌ | ❌ |
| Gemma-3-1B | N/A — text-only, not a VLM | — | — |

## Verdict

Pick **vLLM** if broad model coverage across the research list matters —
it's the only one of the three that can plausibly serve almost everything
above, including several models nothing else (not even the scrapped
`local_vlm.py`/`transformers` approach, not NIM/OpenRouter/HF Inference
Providers) could serve at all.

## Sources

- [vLLM supported_models.md](https://raw.githubusercontent.com/vllm-project/vllm/main/docs/models/supported_models.md)
- [llama.cpp docs/multimodal.md](https://raw.githubusercontent.com/ggml-org/llama.cpp/master/docs/multimodal.md)
- [Ollama vision models search](https://ollama.com/search?c=vision)
- [Ollama moondream](https://ollama.com/library/moondream)
- [Qwen2.5-VL 7B Instruct - OpenRouter](https://openrouter.ai/qwen/qwen-2.5-vl-7b-instruct)
- [Qwen3 VL 8B Instruct - OpenRouter](https://openrouter.ai/qwen/qwen3-vl-8b-instruct)
- [phi-3.5-vision-instruct - NVIDIA NIM](https://build.nvidia.com/microsoft/phi-3_5-vision-instruct/modelcard)
