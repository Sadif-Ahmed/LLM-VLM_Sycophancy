import base64
import io
import json
import logging
import time
import threading
from typing import Any, Callable

import fitz  # PyMuPDF
import httpx
from PIL import Image
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

# NVIDIA NIM Llama vision models cap input images at 1120x1120.
MAX_IMAGE_DIM = 1120


def pdf_to_base64_images(pdf_path: str, jpeg_quality: int = 85) -> list[str]:
    """
    Convert a PDF file to a list of base64 encoded JPEG images (one per page).
    Each page is rendered at a zoom level that keeps the longest edge ≤ MAX_IMAGE_DIM.
    JPEG is used instead of PNG for ~3x smaller payloads, staying within
    NVIDIA's inline base64 size limits.
    """
    base64_images = []
    try:
        doc = fitz.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            # Calculate zoom so the longest edge fits within MAX_IMAGE_DIM
            rect = page.rect  # page dimensions in points (72 DPI)
            page_w, page_h = rect.width, rect.height
            longest = max(page_w, page_h)
            zoom = min(MAX_IMAGE_DIM / longest, 2.0)  # cap at 2x for quality
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            # Convert to JPEG via PIL for compression
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            if img.mode == "RGBA":
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=jpeg_quality)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            base64_images.append(b64)
        doc.close()
    except Exception as e:
        logger.error(f"Failed to convert PDF to images: {e}")
        raise RuntimeError(f"Could not read or convert PDF: {pdf_path}") from e
    return base64_images


def resize_image_to_fit(b64_image: str, max_dim: int = MAX_IMAGE_DIM) -> str:
    """
    Resize a base64 image so its longest edge is ≤ max_dim.
    Returns the (possibly unchanged) base64 string as JPEG.
    """
    img = Image.open(io.BytesIO(base64.b64decode(b64_image)))
    w, h = img.size
    if w <= max_dim and h <= max_dim:
        return b64_image

    scale = max_dim / max(w, h)
    new_w, new_h = int(w * scale), int(h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    if img.mode == "RGBA":
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# Global state for rate limiting (40 RPM limit = 1.5s between requests)
_last_request_time = 0.0
_rate_limit_lock = threading.Lock()

def _enforce_rate_limit(rpm: int = 40):
    global _last_request_time
    min_interval = 60.0 / rpm
    with _rate_limit_lock:
        now = time.time()
        elapsed = now - _last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _last_request_time = time.time()


@retry(
    wait=wait_exponential(multiplier=2, min=5, max=90),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _do_nvidia_call(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    image_b64: str | None = None,
    schema: dict[str, Any] | None = None,
    temperature: float = 0.1,
    max_tokens: int = 32768,
    validate: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """
    Inner function: Call NVIDIA NIM endpoint with exponential backoff.
    Accepts at most ONE base64 image (NVIDIA NIM limit).
    """
    _enforce_rate_limit(rpm=40)
    
    client = OpenAI(
        base_url=NVIDIA_BASE_URL,
        api_key=api_key,
        max_retries=0,  # Disable built-in retries (sub-second backoff); tenacity handles retries with 60s backoff
        timeout=httpx.Timeout(600.0, connect=10.0),  # 600s read, 10s connect
    )

    messages = []
    
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # Build the user message content array
    user_content = [{"type": "text", "text": user_prompt}]
    
    if image_b64:
        # Ensure the image fits within the model's resolution limit
        image_b64 = resize_image_to_fit(image_b64)
        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{image_b64}"
            }
        })
            
    messages.append({"role": "user", "content": user_content})

    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if schema:
        # Pass the schema via standard OpenAI response_format
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "evaluation_response",
                "strict": True,
                "schema": schema
            }
        }

    try:
        response = client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        content = choice.message.content

        if content is None:
            raise ValueError("Model returned empty content (None) — may be a refusal or transient error")

        if choice.finish_reason == "length":
            raise ValueError(
                f"Response truncated at max_tokens={max_tokens} (finish_reason=length) — "
                "output was cut off mid-generation, would silently corrupt structured data"
            )

        # If the model returned JSON wrapped in markdown blocks, strip it before parsing.
        if schema:
            clean_content = content.strip()
            if clean_content.startswith("```json"):
                clean_content = clean_content[7:]
            if clean_content.endswith("```"):
                clean_content = clean_content[:-3]
            result = json.loads(clean_content)
        else:
            result = {"content": content}

        if validate:
            validate(result)  # raises on incomplete/invalid output -> retried like any other failure
        return result
            
    except Exception as e:
        logger.error(f"NVIDIA API call failed: {e}")
        raise


def call_nvidia_structured(
    api_key: str,
    model: str | list[str],
    system_prompt: str,
    user_prompt: str,
    image_b64: str | None = None,
    schema: dict[str, Any] | None = None,
    temperature: float = 0.1,
    max_tokens: int = 32768,
    validate: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """
    Call NVIDIA NIM, with support for model fallbacks.
    Accepts at most ONE base64 image per call.

    If `validate` is given, it's called on the parsed JSON result (schema
    calls only) and should raise if the result is incomplete/invalid — that
    triggers the same per-model retry (tenacity) and pool fallback (below)
    as a hard API failure would.
    """
    models_to_try = [model] if isinstance(model, str) else model

    last_err = None
    for m in models_to_try:
        try:
            logger.info(f"Attempting API call with model: {m}")
            return _do_nvidia_call(
                api_key=api_key,
                model=m,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                image_b64=image_b64,
                schema=schema,
                temperature=temperature,
                max_tokens=max_tokens,
                validate=validate,
            )
        except Exception as e:
            logger.warning(f"Model {m} failed after all retries: {e}")
            last_err = e
            continue
            
    raise RuntimeError(f"All models failed. Last error: {last_err}")
