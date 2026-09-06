"""One-shot probe: replicate encode_example to see exactly what the SFT labels contained."""

import modal

app = modal.App("debug-format")
image = modal.Image.debian_slim(python_version="3.11").pip_install("transformers==4.57.6", "jinja2")
VOL_DIR = "/root/qwen3-a1"
volume = modal.Volume.from_name("qwen3-a1")
BASE = "Qwen/Qwen3-1.7B-Base"


@app.function(image=image, volumes={VOL_DIR: volume}, timeout=900)
def probe():
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(f"{VOL_DIR}/models/{BASE}")
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    messages = [{"role": "user", "content": "हलो"},
                {"role": "assistant", "content": "हाँ मैम बोलिए"}]
    prompt_ids = tok.apply_chat_template(messages[:1], add_generation_prompt=True)
    full_ids = tok.apply_chat_template(messages, add_generation_prompt=False)
    print("PROMPT_TEXT", repr(tok.decode(prompt_ids)))
    print("FULL_TEXT", repr(tok.decode(full_ids)))
    print("LABEL_TEXT", repr(tok.decode(full_ids[len(prompt_ids):])))
    print("PROMPT_LEN", len(prompt_ids), "FULL_LEN", len(full_ids))


@app.local_entrypoint()
def main():
    probe.remote()
