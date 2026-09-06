"""Serving: Qwen3-1.7B + trained DoRA adapter behind a Modal endpoint.

Gate G5: check_serving.py asserts warm server-side first-token latency < 200 ms.
Production upgrade (named ceiling): vLLM multi-LoRA hot-swap serving.

Deploy:
    .venv/bin/modal deploy research/training/serve_qwen3.py
"""

import time

import modal

app = modal.App("qwen3-a1-serve")
image = modal.Image.debian_slim(python_version="3.11").uv_pip_install(
    "torch==2.8.0", "transformers==4.57.6", "peft==0.20.0", "fastapi[standard]==0.141.1",
)
VOL_DIR = "/root/qwen3-a1"
volume = modal.Volume.from_name("qwen3-a1")
BASE_MODEL = "Qwen/Qwen3-1.7B-Base"

_STATE = {}


def load_model():
    """Lazy one-time load inside the warm container."""
    if "model" in _STATE:
        return
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    local_model = f"{VOL_DIR}/models/{BASE_MODEL}"
    tokenizer = AutoTokenizer.from_pretrained(local_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    base = AutoModelForCausalLM.from_pretrained(local_model, torch_dtype=torch.bfloat16)
    model = PeftModel.from_pretrained(base, f"{VOL_DIR}/adapter_a2").to("cuda").eval()
    im_end = tokenizer.convert_tokens_to_ids("<|im_end|>")
    _STATE.update(model=model, tokenizer=tokenizer, eos_ids=[im_end, tokenizer.eos_token_id])
    with torch.no_grad():
        warmup_ids = tokenizer("warmup", return_tensors="pt").input_ids.to(model.device)
        for _ in range(3):
            model.generate(warmup_ids, max_new_tokens=1, do_sample=False,
                           pad_token_id=tokenizer.pad_token_id)


UI_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Awaaz — Hindi/Telugu model</title>
<style>
 body { font-family: system-ui, sans-serif; background: #0f1220; color: #e8eaf6; margin: 0; display: flex; justify-content: center; }
 .wrap { width: 100%; max-width: 640px; padding: 16px; }
 h1 { font-size: 18px; margin: 8px 0 2px; }
 .sub { color: #8a91b4; font-size: 12px; margin-bottom: 14px; }
 #chat { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
 .msg { padding: 10px 14px; border-radius: 14px; max-width: 85%; white-space: pre-wrap; line-height: 1.5; }
 .user { align-self: flex-end; background: #3a4bf0; }
 .model { align-self: flex-start; background: #232741; }
 .meta { font-size: 10px; color: #6c74a8; margin-top: 6px; }
 .row { display: flex; gap: 8px; }
 input { flex: 1; padding: 12px 14px; border-radius: 10px; border: 1px solid #2c3157; background: #171a2e; color: #e8eaf6; font-size: 16px; }
 button { padding: 12px 18px; border-radius: 10px; border: 0; background: #3a4bf0; color: white; font-size: 15px; }
 .hint { color: #6c74a8; font-size: 11px; margin-top: 10px; }
</style>
</head>
<body><div class="wrap">
<h1>Awaaz — Hindi/Telugu model</h1>
<div class="sub">Bilingual call-style conversational model (Qwen3-1.7B + DoRA adapter). First message may take ~1 min (container warm-up).</div>
<div id="chat"></div>
<div class="row"><input id="q" placeholder="Type Hindi or Telugu..." autocomplete="off"><button onclick="send()">Send</button></div>
<div class="hint">Try: హలో &middot; నమస్కారం, నాకు ఒక టికెట్ క్యాన్సల్ చేయాలి &middot; हलो &middot; मुझे एक टिकट कैंसिल करना है</div>
<script>
const API = "https://raj315920--qwen3-a1-serve-first-token.modal.run";
const chat = document.getElementById("chat");
function add(cls, text) {
  const d = document.createElement("div"); d.className = "msg " + cls; d.textContent = text;
  chat.appendChild(d); window.scrollTo(0, document.body.scrollHeight); return d;
}
async function send() {
  const q = document.getElementById("q"); const text = q.value.trim(); if (!text) return;
  q.value = ""; add("user", text);
  const pending = add("model", "...");
  try {
    const r = await fetch(API, { method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ messages: [{role: "user", content: text}], max_tokens: 50 }) });
    const j = await r.json();
    pending.textContent = j.token;
    const m = document.createElement("div"); m.className = "meta";
    m.textContent = j.server_ms + " ms server-side"; pending.appendChild(m);
  } catch (e) { pending.textContent = "Error: " + e; }
}
document.getElementById("q").addEventListener("keydown", e => { if (e.key === "Enter") send(); });
</script>
</div></body></html>"""


@app.function(image=image)
@modal.fastapi_endpoint(method="GET")
def ui():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(UI_HTML)


@app.function(gpu="H100", image=image, volumes={VOL_DIR: volume}, scaledown_window=600)
@modal.fastapi_endpoint(method="POST")
def first_token(payload: dict):
    import torch

    from fastapi import HTTPException

    messages = payload.get("messages")
    if (not isinstance(messages, list) or not messages or not all(
            isinstance(m, dict) and m.get("role") and m.get("content") for m in messages)):
        raise HTTPException(status_code=400, detail="messages must be a non-empty list of {role, content}")
    try:
        max_tokens = max(1, min(int(payload.get("max_tokens", 1)), 256))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="max_tokens must be an integer")

    load_model()
    model = _STATE["model"]
    tokenizer = _STATE["tokenizer"]
    prompt = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt"
    )
    t0 = time.perf_counter()
    with torch.no_grad():
        out = model.generate(
            prompt.to(model.device), max_new_tokens=max_tokens,
            do_sample=True, temperature=0.8, top_p=0.95,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=_STATE["eos_ids"],
        )
    server_ms = (time.perf_counter() - t0) * 1000
    token = tokenizer.decode(out[0, prompt.shape[1]:], skip_special_tokens=True)
    return {"token": token, "server_ms": round(server_ms, 2)}


if __name__ == "__main__":
    print("Deploy via: .venv/bin/modal deploy research/training/serve_qwen3.py")
