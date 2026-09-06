# Mission: Own the Modal training + serving pipeline in research/training/

## Why
Pass the AI Research Engineer interview and run this pipeline with full confidence: explain and defend every part of the code in `research/training/` — Modal H100 fine-tuning (DoRA), serving under the 200 ms first-token budget — because the three role bullets (memory, fine-tuning emotional conversation models, low-latency serving) are exactly what this code demonstrates.

## Success looks like
- Narrate exactly what happens end-to-end when `modal run` executes (image -> container -> H100 -> volume -> download) without notes
- Explain LoRA vs DoRA, adapter save/load/merge, and why each config value (r=16, alpha=32, bf16) is what it is
- Explain the 200 ms budget: what `server_ms` measures, why server-side, and what vLLM would change
- Modify the training script (steps, rank, dataset size) and re-run it alone, interpreting every log line

## Constraints
- Short sessions, interview timeline soon
- 8 GB Mac — all heavy compute happens on Modal, so lessons teach remote-execution thinking
- Prefers guides + hands-on (runs commands himself); agent explains, never replaces his hands

## Out of scope (for now)
- TTS/ASR voice pipeline internals (V0-V4)
- Go backend / WebSockets
- The 200-conversation benchmark collection
