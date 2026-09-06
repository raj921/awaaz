"""G4 oracle: downloaded QLoRA/DoRA adapter passes structural sanity. Prints ADAPTER_OK."""

import json
import os
import sys
from pathlib import Path

ADAPTER_DIR = Path(os.environ.get("ADAPTER_DIR", "data/checkpoints/qwen3-a1-smoke"))
ATTENTION_TARGETS = {"q_proj", "k_proj", "v_proj", "o_proj"}


def main():
    problems = []
    config_path = ADAPTER_DIR / "adapter_config.json"
    if not config_path.is_file():
        print(f"ADAPTER_FAIL: missing {config_path}", file=sys.stderr)
        return 1
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("r", 0) < 8:
        problems.append(f"r={config.get('r')} too small")
    if config.get("lora_alpha", 0) < config.get("r", 0):
        problems.append("lora_alpha < r")
    targets = set(config.get("target_modules") or [])
    if not targets & ATTENTION_TARGETS:
        problems.append(f"no attention targets in {sorted(targets)}")
    if config.get("task_type") != "CAUSAL_LM":
        problems.append(f"task_type={config.get('task_type')}")
    if not config.get("use_dora"):
        problems.append("use_dora not enabled")
    weights = ADAPTER_DIR / "adapter_model.safetensors"
    if not weights.is_file():
        problems.append("missing adapter_model.safetensors")
    elif weights.stat().st_size < 10_000:
        problems.append(f"weights only {weights.stat().st_size} bytes (broken save)")
    for path in ADAPTER_DIR.iterdir():
        if path.is_file() and path.stat().st_size == 0:
            problems.append(f"zero-byte file: {path.name}")
    if problems:
        for problem in problems:
            print(f"ADAPTER_FAIL: {problem}", file=sys.stderr)
        return 1
    print("ADAPTER_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
