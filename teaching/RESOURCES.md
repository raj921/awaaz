# Modal Training Pipeline Resources

## Knowledge

- [Modal docs: Execution model](https://modal.com/docs/guide/execution_model)
  Authoritative for App / function / container / `.remote()` lifecycle. Use for: what runs where, when containers build and die.
- [Modal docs: Volumes](https://modal.com/docs/guide/volumes)
  Cloud disks that outlive containers; commit semantics. Use for: why `volume.commit()` and how the adapter survives.
- [PEFT docs: LoRA and DoRA configuration](https://huggingface.co/docs/peft/main/en/package_reference/lora)
  The library the training script actually calls (`LoraConfig`, `get_peft_model`, `use_dora`). Use for: every parameter in `train_qwen3_sft.py:94-101`.
- [Paper: DoRA — Weight-Decomposed Low-Rank Adaptation (arXiv:2402.09353)](https://arxiv.org/abs/2402.09353)
  Primary source for why DoRA closes the LoRA-to-full-FT gap. Use for: interview answer on "why DoRA".
- [TRL SFTTrainer docs + HF discussion: `assistant_only_loss` requires generation-marked templates](https://discuss.huggingface.co/t/sfttrainerflags-blocks-assistant-only-loss-true/176210)
  Verified this session: why the repo hand-rolls prompt masking (`train_qwen3_sft.py:53-54`). Use for: defending the collate code.
- [Modal examples: GPU app patterns](https://modal.com/docs/examples)
  Reference implementations for H100 functions, web endpoints, keep_running. Use for: deployment and warm-container questions.

## Wisdom (Communities)

- [Modal Slack](https://modal.com/slack)
  Active infra community, staff answer. Use for: Modal-specific errors, volume/networking questions.
- [r/LocalLLaMA](https://www.reddit.com/r/LocalLLaMA/)
  High-signal fine-tuning practice. Use for: adapter sanity checks, training-loss curves, "is this loss normal".

## Gaps
- No strong Hindi/Telugu fine-tuning community found yet — flag if interview prep needs one.
- Interview-grade "ML system design" practice community not yet sourced.
