"""Download IndicVoices Kaggle mirrors straight into a Modal volume — never the local disk.

kagglehub downloads public datasets anonymously (verified), so no Kaggle credentials needed.
Volume: modal.Volume "indicvoices". Recon first (smallest part), then pull the rest.

Run:
    .venv/bin/modal run research/training/download_indicvoices.py
    .venv/bin/modal run research/training/download_indicvoices.py --dataset sunnysome/indicvoices-r-p2
"""

import modal

app = modal.App("indicvoices-download")
image = modal.Image.debian_slim(python_version="3.11").pip_install("kagglehub")
VOL_DIR = "/root/indicvoices"
volume = modal.Volume.from_name("indicvoices", create_if_missing=True)


@app.function(image=image, volumes={VOL_DIR: volume}, timeout=3600)
def download(handle: str, subpath: str = ""):
    import os

    os.environ["KAGGLEHUB_CACHE"] = f"{VOL_DIR}/kagglehub"
    import kagglehub

    if subpath:
        local = kagglehub.dataset_download(handle, path=subpath)
        print(f"PART_DONE {handle}/{subpath} -> {local}")
        if subpath.endswith(".json"):
            print(open(local).read()[:600])
        volume.commit()
        return

    root = kagglehub.dataset_download(handle)
    print(f"DOWNLOAD_DONE {handle} -> {root}")

    total = 0
    groups = {}
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            size = os.path.getsize(fp)
            total += size
            rel = os.path.relpath(fp, root)
            top = rel.split(os.sep)[0]
            groups[top] = groups.get(top, [0, 0])
            groups[top][0] += 1
            groups[top][1] += size
    print(f"TOTAL {total / 1e9:.2f} GB under {root}")
    for top, (n, b) in sorted(groups.items(), key=lambda x: -x[1][1]):
        print(f"  {top}: {n} files, {b / 1e9:.2f} GB")

    paths = []
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            paths.append(os.path.relpath(os.path.join(dirpath, f), root))
    for p in sorted(paths)[:40]:
        print("  FILE", p)
    volume.commit()
    print("VOLUME_COMMITTED")


@app.function(image=image, volumes={VOL_DIR: volume}, timeout=1800)
def labels(handle: str):
    import csv
    import os
    from collections import Counter

    os.environ["KAGGLEHUB_CACHE"] = f"{VOL_DIR}/kagglehub"
    import kagglehub

    local = kagglehub.dataset_download(handle, path="indicvoices_r_labels.csv")
    print(f"LABELS {handle} -> {local} ({os.path.getsize(local)} bytes)")
    with open(local, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    cols = list(rows[0].keys())
    print("COLUMNS", cols)
    lang_col = next((c for c in cols if c.lower() in ("language", "lang", "locale")), cols[0])
    print("LANG_COUNTS", Counter(r[lang_col] for r in rows).most_common())
    task_col = next((c for c in cols if "task" in c.lower()), None)
    if task_col:
        print("TASK_COUNTS", Counter(r[task_col] for r in rows).most_common(12))
    for r in rows[:3]:
        print("SAMPLE", {k: str(v)[:90] for k, v in r.items()})
    volume.commit()


INSPECT_IMAGE = image.pip_install("pyarrow")


@app.function(image=INSPECT_IMAGE, volumes={VOL_DIR: volume}, timeout=1800)
def inspect(root: str = "kagglehub/datasets/neh1277/indicvoices-hindi-1/versions/1"):
    import os
    from collections import Counter

    import pyarrow.parquet as pq

    base = os.path.join(VOL_DIR, root)
    exts = Counter()
    part2 = []
    for dirpath, _, filenames in os.walk(base):
        for f in filenames:
            exts[os.path.splitext(f)[1] or "(none)"] += 1
            if "part_002" in dirpath:
                part2.append(os.path.relpath(os.path.join(dirpath, f), base))
    print("EXTS", dict(exts))
    print("PART2_SAMPLE", sorted(part2)[:15], "total:", len(part2))

    shards = []
    for dirpath, _, filenames in os.walk(base):
        for f in sorted(filenames):
            if f.endswith(".parquet"):
                shards.append(os.path.join(dirpath, f))
                break
    shard = shards[0]
    table = pq.read_table(shard)
    print("SHARD", os.path.basename(shard), "rows:", table.num_rows)
    print("SCHEMA", [(f.name, str(f.type)[:20]) for f in table.schema])

    sample = table.slice(0, 3).to_pylist()
    for i, row in enumerate(sample):
        flat = {}
        for k, v in row.items():
            if isinstance(v, dict):
                flat[k] = "AUDIO bytes=" + str(len(v.get("bytes") or b""))
            elif isinstance(v, bytes):
                flat[k] = "bytes=" + str(len(v))
            else:
                flat[k] = str(v)[:120]
        print("ROW", i, flat)

    cols = [f.name for f in table.schema]
    task_col = next((c for c in cols if "task" in c.lower() or "prompt" in c.lower() or "context" in c.lower()), None)
    if task_col:
        head = pq.read_table(shard, columns=[task_col]).to_pylist()
        counts = Counter(str(r[task_col])[:60] for r in head)
        print("TASK_COUNTS", counts.most_common(15))
    volume.commit()


@app.function(image=INSPECT_IMAGE, volumes={VOL_DIR: volume}, timeout=3600)
def extract(root: str = "kagglehub/datasets/neh1277/indicvoices-hindi-1/versions/1",
            out_name: str = "indicvoices_hindi_transcripts.jsonl"):
    import glob
    import json
    import os
    import shutil
    from collections import Counter

    import pyarrow.parquet as pq

    base = os.path.join(VOL_DIR, root)
    all_shards = sorted(glob.glob(os.path.join(base, "**", "*.parquet"), recursive=True))
    unique = {}
    for shard in all_shards:
        unique.setdefault(os.path.basename(shard), shard)
    print(f"PARQUET_SHARDS total={len(all_shards)} unique={len(unique)}")
    if len(unique) < len(all_shards):
        print(f"DUPES {len(all_shards) - len(unique)} duplicate shard names skipped")

    out_path = os.path.join(VOL_DIR, "extracted", out_name)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    keep_cols = ["text", "normalized", "scenario", "task_name", "speaker_id",
                 "gender", "age_group", "duration", "lang"]
    scenarios = Counter()
    rows_written = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for name in sorted(unique):
            table = pq.read_table(unique[name], columns=keep_cols)
            for rec in table.to_pylist():
                scenarios[rec["scenario"]] += 1
                rec["shard"] = name
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                rows_written += 1
    print(f"EXTRACT_DONE rows={rows_written} bytes={os.path.getsize(out_path)} -> {out_path}")
    print("SCENARIOS", scenarios.most_common(20))

    p1 = os.path.join(VOL_DIR, "kagglehub/datasets/someoneind/indicvoices-r-p1/versions/2")
    for sub in ("indicvoices_r", "indicvoices_r_audio"):
        target = os.path.join(p1, sub)
        if os.path.isdir(target):
            shutil.rmtree(target)
            print("DELETED", sub)
    volume.commit()
    print("VOLUME_COMMITTED")


@app.function(image=image, volumes={VOL_DIR: volume}, timeout=3600)
def build_sft(train_pairs: int = 20000, val_pairs: int = 500, context_turns: int = 3, seed: int = 20260902):
    import json
    import os
    import random

    random.seed(seed)
    path = os.path.join(VOL_DIR, "extracted", "indicvoices_hindi_transcripts.jsonl")
    blocks, cur, cur_spk = [], [], None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec["scenario"] != "Conversation":
                continue
            if rec["speaker_id"] != cur_spk:
                if len(cur) >= 2:
                    blocks.append(cur)
                cur, cur_spk = [], rec["speaker_id"]
            text = rec["text"].strip()
            if 0.5 <= rec["duration"] <= 30 and len(text) >= 2:
                cur.append(text)
    if len(cur) >= 2:
        blocks.append(cur)
    print(f"BLOCKS {len(blocks)} utterances {sum(len(b) for b in blocks)}")
    random.shuffle(blocks)

    def pairs_from(block):
        out = []
        for i in range(1, len(block)):
            ctx = "\n".join(block[max(0, i - context_turns):i])
            out.append((ctx, block[i]))
        return out

    train, val, seen = [], [], set()
    for b in blocks:
        if len(val) < val_pairs:
            val.extend(pairs_from(b))
            continue
        for ctx, target in pairs_from(b):
            key = ctx + "\u241f" + target
            if key in seen:
                continue
            seen.add(key)
            train.append({"messages": [{"role": "user", "content": ctx},
                                       {"role": "assistant", "content": target}]})
        if len(train) >= train_pairs:
            break
    train = train[:train_pairs]
    val = [{"messages": [{"role": "user", "content": c}, {"role": "assistant", "content": t}]}
           for c, t in val]

    out_dir = os.path.join(VOL_DIR, "extracted")
    for name, data in (("a1_sft_train.jsonl", train), ("a1_sft_val.jsonl", val)):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
            for ex in data:
                fh.write(json.dumps(ex, ensure_ascii=False) + "\n")
    sample = train[0]["messages"]
    print(f"SFT_BUILD_DONE train={len(train)} val={len(val)} blocks={len(blocks)}")
    print("SAMPLE_USER", sample[0]["content"][:120])
    print("SAMPLE_ASSISTANT", sample[1]["content"][:120])
    volume.commit()


@app.function(image=image, volumes={VOL_DIR: volume}, timeout=3600)
def build_bilingual(train_per_lang: int = 10000, val_per_lang: int = 250, context_turns: int = 3, seed: int = 20260903):
    import json
    import os
    import random

    random.seed(seed)
    out_dir = os.path.join(VOL_DIR, "extracted")

    def blocks_from(fname):
        blocks, cur, cur_spk = [], [], None
        with open(os.path.join(out_dir, fname), encoding="utf-8") as fh:
            for line in fh:
                rec = json.loads(line)
                if rec["scenario"] != "Conversation":
                    continue
                if rec["speaker_id"] != cur_spk:
                    if len(cur) >= 2:
                        blocks.append(cur)
                    cur, cur_spk = [], rec["speaker_id"]
                text = rec["text"].strip()
                if 0.5 <= rec["duration"] <= 30 and len(text) >= 2:
                    cur.append(text)
        if len(cur) >= 2:
            blocks.append(cur)
        random.shuffle(blocks)
        return blocks

    def pairs_from(block):
        return [("\n".join(block[max(0, i - context_turns):i]), block[i]) for i in range(1, len(block))]

    train, val, seen, stats = [], [], set(), {}
    for fname, lang in (("indicvoices_hindi_transcripts.jsonl", "hi"), ("indicvoices_telugu_transcripts.jsonl", "te")):
        got_train = got_val = 0
        for b in blocks_from(fname):
            ps = pairs_from(b)
            if got_val < val_per_lang:
                val.extend({"messages": [{"role": "user", "content": c}, {"role": "assistant", "content": t}]}
                           for c, t in ps)
                got_val += len(ps)
                continue
            for c, t in ps:
                key = c + "\u241f" + t
                if key in seen:
                    continue
                seen.add(key)
                train.append({"messages": [{"role": "user", "content": c}, {"role": "assistant", "content": t}]})
                got_train += 1
            if got_train >= train_per_lang:
                break
        stats[lang] = {"train": min(got_train, train_per_lang), "val": got_val}
    random.shuffle(train)
    for name, data in (("a2_sft_train.jsonl", train), ("a2_sft_val.jsonl", val)):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
            for ex in data:
                fh.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"BI_SFT_BUILD_DONE train={len(train)} val={len(val)} per_lang={stats}")
    volume.commit()


@app.function(image=image, volumes={VOL_DIR: volume}, timeout=1800)
def verify_sft(train_name: str = "a1_sft_train.jsonl", val_name: str = "a1_sft_val.jsonl",
               min_train: int = 19000, min_val: int = 400):
    import json
    import os

    out_dir = os.path.join(VOL_DIR, "extracted")
    problems = []
    stats = {}
    for name, minimum in ((train_name, min_train), (val_name, min_val)):
        rows = []
        with open(os.path.join(out_dir, name), encoding="utf-8") as fh:
            for line in fh:
                rows.append(json.loads(line))
        empty = sum(1 for r in rows if not r["messages"][0]["content"].strip() or not r["messages"][1]["content"].strip())
        indic = sum(1 for r in rows if any("\u0900" <= c <= "\u097f" or "\u0c00" <= c <= "\u0c7f" for c in r["messages"][1]["content"]))
        stats[name] = f"rows={len(rows)} empty={empty} indic={indic / len(rows):.3f}"
        if len(rows) < minimum:
            problems.append(f"{name}: only {len(rows)} rows")
        if empty:
            problems.append(f"{name}: {empty} empty contents")
        if indic / len(rows) < 0.9:
            problems.append(f"{name}: indic ratio {indic / len(rows):.3f} < 0.9")
    for k, v in stats.items():
        print(k, v)
    if problems:
        for p in problems:
            print("SFT_FAIL:", p)
        return 1
    print("SFT_OK")
    volume.commit()
    return 0


HF_IMAGE = image.pip_install("huggingface_hub")
HF_SECRET = modal.Secret.from_name("hf-indicvoices", required_keys=["HF_TOKEN"])


@app.function(image=HF_IMAGE, secrets=[HF_SECRET], volumes={VOL_DIR: volume}, timeout=7200)
def hf_pull(repo: str = "ai4bharat/IndicVoices", pattern: str = "", list_only: bool = True):
    import os
    from collections import Counter

    from huggingface_hub import list_repo_files, snapshot_download

    token = os.environ["HF_TOKEN"]
    files = list_repo_files(repo, repo_type="dataset", token=token)
    tops = Counter(f.split("/")[0] for f in files)
    print(f"REPO_FILES total={len(files)}")
    print("TOP_LEVEL", tops.most_common(30))
    hits = [f for f in files if not pattern or pattern.lower() in f.lower() or f"/{pattern.lower()}/" in f.lower()]
    print(f"PATTERN_MATCHES pattern={pattern!r} count={len(hits)}")
    for f in hits[:80]:
        print("  FILE", f)
    if list_only:
        return
    allow = [f"*{pattern}*"] if pattern else None
    snapshot_download(repo, repo_type="dataset", allow_patterns=allow,
                      local_dir=f"{VOL_DIR}/hf/{repo.split('/')[-1]}", token=token)
    volume.commit()
    print("HF_DOWNLOAD_DONE")


@app.function(image=image, volumes={VOL_DIR: volume}, timeout=1800)
def convo_probe(limit: int = 3000):
    import json
    import os

    path = os.path.join(VOL_DIR, "extracted", "indicvoices_hindi_transcripts.jsonl")
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec["scenario"] == "Conversation":
                rows.append(rec)
            if len(rows) >= limit:
                break
    print(f"CONVO_ROWS_READ {len(rows)}")

    prev = None
    runs = []
    cur_len = 0
    transitions = 0
    for r in rows:
        if r["speaker_id"] == prev:
            cur_len += 1
        else:
            if prev is not None:
                runs.append(cur_len)
                transitions += 1
            prev = r["speaker_id"]
            cur_len = 1
    runs.append(cur_len)
    from collections import Counter
    print("SPEAKER_TRANSITIONS", transitions, "run-length top:", Counter(runs).most_common(10))

    print("FIRST_40 (idx | spk_tail | dur | text[:55]):")
    for i, r in enumerate(rows[:40]):
        print(f"  {i} | {r['speaker_id'][-6:]} | {r['duration']} | {r['text'][:55]}")
    volume.commit()


@app.local_entrypoint()
def main(dataset: str = "someoneind/indicvoices-r-p1", subpath: str = "", probe_labels: bool = False,
         inspect_parquet: bool = False, extract_transcripts: bool = False, probe_convo: bool = False,
         build_a1_sft: bool = False, verify_a1_sft: bool = False, hf_mode: str = "", hf_pattern: str = "",
         extract_lang: str = "", build_a2_bilingual: bool = False, verify_a2_sft: bool = False):
    if build_a2_bilingual:
        build_bilingual.remote()
        verify_sft.remote(train_name="a2_sft_train.jsonl", val_name="a2_sft_val.jsonl")
        return
    if verify_a2_sft:
        verify_sft.remote(train_name="a2_sft_train.jsonl", val_name="a2_sft_val.jsonl")
        return
    if extract_lang == "telugu":
        extract.remote(root="hf/IndicVoices/telugu", out_name="indicvoices_telugu_transcripts.jsonl")
        return
    if hf_mode:
        hf_pull.remote(pattern=hf_pattern, list_only=(hf_mode == "list"))
        return
    if build_a1_sft:
        build_sft.remote()
        verify_sft.remote()
        return
    if verify_a1_sft:
        verify_sft.remote()
        return
    if probe_convo:
        convo_probe.remote()
        return
    if inspect_parquet:
        extract.remote()
        return
    if probe_labels:
        for handle in ("someoneind/indicvoices-r-p1", "sunnysome/indicvoices-r-p2",
                       "sunnysome/indicvoices-r-p3", "someoneind/indicvoices-r-p4"):
            labels.remote(handle)
        return
    download.remote(dataset, subpath)
    if not subpath:
        for part in ("sunnysome/indicvoices-r-p2", "sunnysome/indicvoices-r-p3", "someoneind/indicvoices-r-p4"):
            download.remote(part, "__huggingface_repos__.json")
