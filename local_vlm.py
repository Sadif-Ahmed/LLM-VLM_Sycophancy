"""
Local (in-process) VLM inference via Hugging Face `transformers`, run on this
machine's own GPU/CPU — no API key, no per-request network call, no rate
limit or per-token cost. Only the model weights are fetched once (from the
HF Hub, cached under ~/.cache/huggingface).

call_local() mirrors conversation_sim.call_llm()'s (messages, temperature,
max_tokens) -> (content, usage) shape, so it drops into the existing probe
scripts' message-building code (system_prompts.json / pushback_prompts.json,
strip_images_except_last, etc.) unchanged — only the call site swaps.

Model + processor are loaded once per process, lazily, and cached by model_id
so a probe run's many turns/items reuse the same weights already on-device.
"""
import base64
import io

import torch
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor

_MODEL_CACHE: dict[str, tuple] = {}


def _load(model_id: str):
    if model_id not in _MODEL_CACHE:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        processor = AutoProcessor.from_pretrained(model_id)
        model = AutoModelForImageTextToText.from_pretrained(model_id, dtype=dtype).to(device)
        model.eval()
        _MODEL_CACHE[model_id] = (processor, model, device, dtype)
    return _MODEL_CACHE[model_id]


def _decode_image(data_url: str) -> Image.Image:
    b64 = data_url.split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")


def _to_hf_messages(messages: list[dict]) -> tuple[list[dict], list[Image.Image]]:
    """OpenAI-style messages (content is a plain str, or a list of
    {"type": "text", ...} / {"type": "image_url", ...} parts) -> the chat
    format SmolVLM/Idefics3-family processors expect (every content is a
    list of {"type": "text", "text": ...} / {"type": "image"} parts), plus
    the flat, in-order list of decoded PIL images each {"type": "image"}
    placeholder refers to."""
    hf_messages = []
    images = []
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            hf_messages.append({"role": m["role"], "content": [{"type": "text", "text": content}]})
            continue
        parts = []
        for p in content:
            if p["type"] == "text":
                parts.append({"type": "text", "text": p["text"]})
            elif p["type"] == "image_url":
                images.append(_decode_image(p["image_url"]["url"]))
                parts.append({"type": "image"})
        hf_messages.append({"role": m["role"], "content": parts})
    return hf_messages, images


def call_local(model_id: str, messages: list[dict], temperature: float, max_tokens: int) -> tuple[str, dict | None]:
    processor, model, device, dtype = _load(model_id)
    hf_messages, images = _to_hf_messages(messages)

    prompt = processor.apply_chat_template(hf_messages, add_generation_prompt=True)
    inputs = processor(text=prompt, images=images or None, return_tensors="pt").to(device)
    if "pixel_values" in inputs:
        inputs["pixel_values"] = inputs["pixel_values"].to(dtype)
    input_len = inputs["input_ids"].shape[1]

    gen_kwargs = {"max_new_tokens": max_tokens, "do_sample": temperature > 0}
    if temperature > 0:
        gen_kwargs["temperature"] = temperature

    with torch.no_grad():
        out = model.generate(**inputs, **gen_kwargs)

    gen_ids = out[:, input_len:]
    content = processor.batch_decode(gen_ids, skip_special_tokens=True)[0].strip()
    if not content:
        raise ValueError("Model returned empty content — refusal or a generation stopping on the very first token")
    usage = {
        "prompt_tokens": input_len,
        "completion_tokens": int(gen_ids.shape[1]),
        "total_tokens": int(out.shape[1]),
    }
    return content, usage
