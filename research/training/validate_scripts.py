"""G3 oracle: structural validation of the Modal apps via AST — no GPU, no modal import.

Comments are invisible to AST parsing, so scaffolds cannot pass by mentioning
markers in prose. Prints TRAIN_SCRIPTS_OK only when every assertion holds.
"""

import ast
import sys
from pathlib import Path


def inspect(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    names, attrs, constants, keywords = set(), set(), set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            attrs.add(node.attr)
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                keywords.add(kw.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            constants.add(node.value)
    return names, attrs, constants, keywords


def require(found, marker, missing, label):
    names, attrs, constants, keywords = found
    present = marker in names | attrs | keywords or any(marker in c for c in constants)
    if not present:
        missing.append(f"{label}: missing {marker!r}")


def main():
    train = inspect("research/training/train_qwen3_sft.py")
    serve = inspect("research/training/serve_qwen3.py")
    missing = []
    for marker in ("App", "train", "LoraConfig", "q_proj", "save_pretrained", "H100", "TRAIN_DONE",
                   "add_local_file", "snapshot_download", "train_a1", "TRAIN_A1_DONE", "a1_sft_train",
                   "train_a2", "TRAIN_A2_DONE", "a2_sft_train",
                   "train_a3", "TRAIN_A3_DONE", "adapter_a3"):
        require(train, marker, missing, "train_qwen3_sft.py")
    require(train, "use_dora", missing, "train_qwen3_sft.py")
    for marker in ("fastapi_endpoint", "scaledown_window", "perf_counter", "PeftModel", "cuda", "server_ms", "adapter_a2"):
        require(serve, marker, missing, "serve_qwen3.py")
    if missing:
        for line in missing:
            print(f"MISSING: {line}", file=sys.stderr)
        return 1
    print("TRAIN_SCRIPTS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
