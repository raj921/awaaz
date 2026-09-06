"""Qwen3-1.7B-Base DoRA SFT on Modal H100: smoke, Hindi A1, bilingual A2, and a base-vs-tuned bench.

Proves the pipeline end-to-end (smoke), then trains the real adapters:
A1 on 20K Hindi conversation pairs, A2 on 20K bilingual hi+te pairs, both
saved to Volume qwen3-a1 and served by serve_qwen3.py. The bench compares
base vs tuned eval loss on the held-out A2 set.

Run:
    .venv/bin/modal run research/training/train_qwen3_sft.py --step-mode smoke
    .venv/bin/modal run research/training/train_qwen3_sft.py --step-mode a1 --max-steps 2500
    .venv/bin/modal run research/training/train_qwen3_sft.py --step-mode a2 --max-steps 2500
    .venv/bin/modal run research/training/train_qwen3_sft.py --step-mode bench
    .venv/bin/modal volume get qwen3-a1 adapter_a2 data/checkpoints/qwen3-a2-bilingual
"""

import json

import modal

app = modal.App("qwen3-a1-sft")
image = modal.Image.debian_slim(python_version="3.11").uv_pip_install(
    "torch==2.8.0", "transformers==4.57.6", "peft==0.20.0", "accelerate==1.14.0",
).env({"HF_XET_HIGH_PERFORMANCE": "1", "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"}).add_local_file(
    "data/raw/masac_erc/MaSaC_train_erc.json", "/root/masac_train.json"
)
VOL_DIR = "/root/qwen3-a1"
MODEL_DIR = f"{VOL_DIR}/models"
volume = modal.Volume.from_name("qwen3-a1", create_if_missing=True)
indic_vol = modal.Volume.from_name("indicvoices")
INDIC_DIR = "/root/indicvoices"
A1_TRAIN = f"{INDIC_DIR}/extracted/a1_sft_train.jsonl"
A1_VAL = f"{INDIC_DIR}/extracted/a1_sft_val.jsonl"
A2_TRAIN = f"{INDIC_DIR}/extracted/a2_sft_train.jsonl"
A2_VAL = f"{INDIC_DIR}/extracted/a2_sft_val.jsonl"
BASE_MODEL = "Qwen/Qwen3-1.7B-Base"
TRAIN_GPU = "H200"


def build_examples(path, limit=800):
    """MaSaC dialogues -> user/assistant chat pairs."""
    with open(path, encoding="utf-8") as handle:
        dialogues = json.load(handle)
    examples = []
    for dialogue in dialogues:
        utterances = [u.strip() for u in dialogue["utterances"] if u.strip()]
        for i in range(len(utterances) - 1):
            examples.append({"messages": [
                {"role": "user", "content": utterances[i]},
                {"role": "assistant", "content": utterances[i + 1]},
            ]})
            if len(examples) >= limit:
                return examples
    return examples


def encode_example(tokenizer, example):
    """Chat-template encode; labels = pure assistant content + <|im_end|> (no template think-wrappers)."""
    messages = example["messages"]
    roles = [m["role"] for m in messages]
    if roles != ["user", "assistant"]:
        raise ValueError(f"expected [user, assistant], got {roles}")
    prompt_ids = tokenizer.apply_chat_template(messages[:1], add_generation_prompt=True)
    content_ids = tokenizer(messages[1]["content"], add_special_tokens=False)["input_ids"]
    full_ids = prompt_ids + content_ids + [tokenizer.convert_tokens_to_ids("<|im_end|>")]
    return full_ids, [-100] * len(prompt_ids) + full_ids[len(prompt_ids):]


def collate(batch, pad_id, max_len=512):
    import torch
    items = [(item["input_ids"][-max_len:], item["labels"][-max_len:]) for item in batch]
    longest = max(len(ids) for ids, _ in items)
    input_ids, labels, attention = [], [], []
    for ids, labs in items:
        pad = longest - len(ids)
        input_ids.append(ids + [pad_id] * pad)
        labels.append(labs + [-100] * pad)
        attention.append([1] * len(ids) + [0] * pad)
    return {
        "input_ids": torch.tensor(input_ids),
        "labels": torch.tensor(labels),
        "attention_mask": torch.tensor(attention),
    }


@app.function(image=image, volumes={VOL_DIR: volume}, timeout=1800)
def download_base():
    """Cache the base model on the volume so GPU time is never spent downloading."""
    from huggingface_hub import snapshot_download

    snapshot_download(BASE_MODEL, local_dir=f"{MODEL_DIR}/{BASE_MODEL}")
    volume.commit()
    print(f"BASE_MODEL_CACHED {MODEL_DIR}/{BASE_MODEL}")


@app.function(gpu=TRAIN_GPU, image=image, volumes={VOL_DIR: volume}, timeout=3600)
def train(max_steps=30, lora_r=16, lora_alpha=32, learning_rate=2e-4, batch_size=8):
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments

    local_model = f"{MODEL_DIR}/{BASE_MODEL}"
    tokenizer = AutoTokenizer.from_pretrained(local_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    examples = [{"input_ids": ids, "labels": labels}
                for ids, labels in (encode_example(tokenizer, e) for e in build_examples("/root/masac_train.json"))]
    print(f"TRAIN_DATA examples={len(examples)}")

    model = AutoModelForCausalLM.from_pretrained(local_model, torch_dtype=torch.bfloat16)
    model = get_peft_model(model, LoraConfig(
        r=lora_r, lora_alpha=lora_alpha, lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        task_type="CAUSAL_LM",
        use_dora=True,
    ))
    model.print_trainable_parameters()

    args = TrainingArguments(
        output_dir="/tmp/out", max_steps=max_steps, per_device_train_batch_size=batch_size,
        learning_rate=learning_rate, logging_steps=10, save_strategy="no",
        bf16=True, report_to="none", seed=20260828,
    )
    trainer = Trainer(model=model, args=args, train_dataset=examples,
                      data_collator=lambda batch: collate(batch, tokenizer.pad_token_id))
    trainer.train()

    final_loss = next((entry["loss"] for entry in reversed(trainer.state.log_history) if "loss" in entry), None)
    model.save_pretrained(f"{VOL_DIR}/adapter")
    tokenizer.save_pretrained(f"{VOL_DIR}/adapter")
    volume.commit()
    print(f"TRAIN_DONE steps={max_steps} final_loss={(f'{final_loss:.4f}' if final_loss is not None else 'none')}")


def encode_examples(tokenizer, rows):
    """message dicts -> masked (input_ids, labels) examples."""
    examples = []
    for example in rows:
        ids, labels = encode_example(tokenizer, example)
        examples.append({"input_ids": ids, "labels": labels})
    return examples


def load_sft_examples(tokenizer, path):
    """messages-JSONL -> masked (input_ids, labels) examples."""
    with open(path, encoding="utf-8") as fh:
        return encode_examples(tokenizer, [json.loads(line) for line in fh])


def _fmt_loss(value):
    return f"{value:.4f}" if value is not None else "none"


def train_sft(train_path, val_path, data_tag, out_dir, max_steps=2500, batch_size=8,
              learning_rate=2e-4, warmup_ratio=0.0, scheduler="linear", grad_accum=1,
              targets=("q_proj", "k_proj", "v_proj", "o_proj"), save_best=False):
    """Shared DoRA SFT body. Returns (final_loss, eval_loss)."""
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments

    print(f"TRAIN_GPU {torch.cuda.get_device_name(0)}")
    local_model = f"{MODEL_DIR}/{BASE_MODEL}"
    tokenizer = AutoTokenizer.from_pretrained(local_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    train_examples = load_sft_examples(tokenizer, train_path)
    val_examples = load_sft_examples(tokenizer, val_path)
    print(f"{data_tag}_DATA train={len(train_examples)} val={len(val_examples)}")

    model = AutoModelForCausalLM.from_pretrained(local_model, torch_dtype=torch.bfloat16)
    model = get_peft_model(model, LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05,
        target_modules=list(targets),
        task_type="CAUSAL_LM",
        use_dora=True,
    ))
    model.print_trainable_parameters()

    args = TrainingArguments(
        output_dir="/tmp/out", max_steps=max_steps, per_device_train_batch_size=batch_size,
        learning_rate=learning_rate, logging_steps=100, save_strategy="steps" if save_best else "no",
        save_steps=500, save_total_limit=1,
        eval_strategy="steps", eval_steps=500, warmup_ratio=warmup_ratio,
        lr_scheduler_type=scheduler, gradient_accumulation_steps=grad_accum,
        load_best_model_at_end=save_best,
        bf16=True, report_to="none", seed=20260828,
    )
    trainer = Trainer(model=model, args=args, train_dataset=train_examples,
                      eval_dataset=val_examples,
                      data_collator=lambda batch: collate(batch, tokenizer.pad_token_id))
    trainer.train()

    final_loss = next((entry["loss"] for entry in reversed(trainer.state.log_history) if "loss" in entry), None)
    eval_loss = next((entry["eval_loss"] for entry in reversed(trainer.state.log_history) if "eval_loss" in entry), None)
    model.save_pretrained(f"{VOL_DIR}/{out_dir}")
    tokenizer.save_pretrained(f"{VOL_DIR}/{out_dir}")
    volume.commit()
    return final_loss, eval_loss


@app.function(gpu=TRAIN_GPU, image=image, volumes={VOL_DIR: volume, INDIC_DIR: indic_vol}, timeout=7200)
def train_a1(max_steps=2500, batch_size=8, learning_rate=2e-4):
    final_loss, eval_loss = train_sft(
        A1_TRAIN, A1_VAL, "A1", "adapter", max_steps, batch_size, learning_rate)
    print(f"TRAIN_A1_DONE steps={max_steps} final_loss={_fmt_loss(final_loss)} eval_loss={_fmt_loss(eval_loss)}")


@app.function(gpu=TRAIN_GPU, image=image, volumes={VOL_DIR: volume, INDIC_DIR: indic_vol}, timeout=7200)
def train_a2(max_steps=2500, batch_size=8, learning_rate=2e-4):
    final_loss, eval_loss = train_sft(
        A2_TRAIN, A2_VAL, "A2", "adapter_a2", max_steps, batch_size, learning_rate)
    print(f"TRAIN_A2_DONE steps={max_steps} final_loss={_fmt_loss(final_loss)} eval_loss={_fmt_loss(eval_loss)}")


@app.function(gpu=TRAIN_GPU, image=image, volumes={VOL_DIR: volume, INDIC_DIR: indic_vol}, timeout=7200)
def train_a3(max_steps=7500, batch_size=8, learning_rate=2e-4):
    final_loss, eval_loss = train_sft(
        A2_TRAIN, A2_VAL, "A3", "adapter_a3", max_steps, batch_size, learning_rate,
        warmup_ratio=0.03, scheduler="cosine", grad_accum=2,
        targets=("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"),
        save_best=True)
    print(f"TRAIN_A3_DONE steps={max_steps} final_loss={_fmt_loss(final_loss)} eval_loss={_fmt_loss(eval_loss)}")


@app.function(gpu=TRAIN_GPU, image=image, volumes={VOL_DIR: volume, INDIC_DIR: indic_vol}, timeout=3600)
def bench(adapter: str = "adapter_a2"):
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments

    print(f"BENCH_GPU {torch.cuda.get_device_name(0)}")
    local_model = f"{MODEL_DIR}/{BASE_MODEL}"
    tokenizer = AutoTokenizer.from_pretrained(local_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    with open(A2_VAL, encoding="utf-8") as fh:
        raw = [json.loads(line) for line in fh]

    def is_te(example):
        return any("\u0c00" <= c <= "\u0c7f" for c in example["messages"][1]["content"])

    splits = {"all": raw, "hi": [e for e in raw if not is_te(e)], "te": [e for e in raw if is_te(e)]}

    def run_eval(model, tag):
        out = {}
        args = TrainingArguments(output_dir="/tmp/bench", report_to="none", bf16=True, seed=20260828)
        for name, rows in splits.items():
            trainer = Trainer(model=model, args=args, eval_dataset=encode_examples(tokenizer, rows),
                              data_collator=lambda batch: collate(batch, tokenizer.pad_token_id))
            result = trainer.evaluate()
            out[name] = round(result["eval_loss"], 4)
            print(f"BENCH {tag} {name} n={len(rows)} eval_loss={result['eval_loss']:.4f}")
        return out

    # NOTE: PeftModel.from_pretrained below mutates base in place, so the
    # base-then-tuned eval ordering is load-bearing. Do not reorder.
    base = AutoModelForCausalLM.from_pretrained(local_model, torch_dtype=torch.bfloat16).to("cuda").eval()
    results = {"base": run_eval(base, "base")}
    tuned = PeftModel.from_pretrained(base, f"{VOL_DIR}/{adapter}").eval()
    results["tuned"] = run_eval(tuned, "tuned")
    print("BENCH_RESULT " + json.dumps(results))


@app.local_entrypoint()
def main(step_mode: str = "smoke", max_steps: int = 30, bench_adapter: str = "adapter_a2"):
    if step_mode == "bench":
        bench.remote(adapter=bench_adapter)
        return
    if step_mode == "a3":
        train_a3.remote(max_steps=max_steps)
        return
    if step_mode == "a2":
        train_a2.remote(max_steps=max_steps)
        return
    if step_mode == "a1":
        train_a1.remote(max_steps=max_steps)
        return
    download_base.remote()
    train.remote(max_steps=max_steps)


if __name__ == "__main__":
    print("Run via: .venv/bin/modal run research/training/train_qwen3_sft.py")
