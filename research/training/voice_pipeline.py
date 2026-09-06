"""Voice milestone: STT (whisper) + TTS (indic-parler-tts) + full loop with the bilingual A2 model.

Per-stage latency budgets from research/spec.md (200 ms class, warm). Audio + transcripts
come from the IndicVoices data already on Volume "indicvoices"; model caches + the A2
adapter live on Volume "qwen3-a1". Nothing large ever touches the local disk (except the
tiny demo wavs worth listening to).

Run:
    .venv/bin/modal run research/training/voice_pipeline.py --step prep
    .venv/bin/modal run research/training/voice_pipeline.py --step asr-eval
    .venv/bin/modal run research/training/voice_pipeline.py --step featurize-whisper
    .venv/bin/modal run research/training/voice_pipeline.py --step asr-finetune --whisper-steps 4000 --whisper-save whisper-small-hi-te-v2
    .venv/bin/modal run research/training/voice_pipeline.py --step tts-demo
    .venv/bin/modal run research/training/voice_pipeline.py --step loop
"""

import json

import modal

app = modal.App("voice-pipeline")
image = modal.Image.debian_slim(python_version="3.11").uv_pip_install(
    "torch==2.8.0", "transformers==4.57.6", "peft==0.20.0", "accelerate==1.14.0",
    "soundfile", "librosa", "jiwer", "pyarrow", "fastapi[standard]==0.141.1",
).env({"HF_XET_HIGH_PERFORMANCE": "1", "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"})
tts_image = modal.Image.debian_slim(python_version="3.11").uv_pip_install(
    "torch==2.8.0", "torchaudio==2.8.0", "transformers==4.46.1", "parler-tts", "soundfile",
    "fastapi[standard]==0.141.1",
).env({"HF_XET_HIGH_PERFORMANCE": "1"})
TTS_DESC = ("A female speaker delivers words at a moderate pace in a clear, warm tone, "
            "with high quality audio.")
_TTS_STATE = {}
_VOICE_STATE = {}
VOICE_UI_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Awaaz Voice — hi/te</title>
<style>
 body { font-family: system-ui, sans-serif; background: #0f1220; color: #e8eaf6; margin: 0; display: flex; justify-content: center; }
 .wrap { width: 100%; max-width: 560px; padding: 16px; }
 h1 { font-size: 18px; margin: 8px 0 2px; }
 .sub { color: #8a91b4; font-size: 12px; margin-bottom: 14px; }
 .lang { display: flex; gap: 8px; margin-bottom: 14px; }
 .lang button { border: 1px solid #2c3157; background: #171a2e; color: #8a91b4; border-radius: 20px; padding: 6px 16px; cursor: pointer; }
 .lang button.on { background: #3a4bf0; color: white; border-color: #3a4bf0; }
 button.mic { width: 100%; padding: 18px; font-size: 17px; border-radius: 12px; border: 0; background: #3a4bf0; color: white; cursor: pointer; }
 button.mic.rec { background: #d93025; }
 .row { display: flex; gap: 8px; margin-top: 10px; }
 input { flex: 1; padding: 12px 14px; border-radius: 10px; border: 1px solid #2c3157; background: #171a2e; color: #e8eaf6; font-size: 16px; }
 .send { padding: 12px 18px; border-radius: 10px; border: 0; background: #232741; color: white; font-size: 15px; cursor: pointer; }
 #status { color: #8a91b4; font-size: 13px; margin: 14px 0; min-height: 18px; }
 .card { background: #232741; border-radius: 12px; padding: 14px; margin-bottom: 10px; }
 .lbl { color: #8a91b4; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
 .txt { font-size: 17px; line-height: 1.5; margin-top: 4px; }
 .chips { display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap; }
 .chip { background: #171a2e; border-radius: 12px; font-size: 11px; color: #8a91b4; padding: 4px 10px; }
 audio { width: 100%; margin-top: 10px; }
</style>
</head>
<body><div class="wrap">
<h1>Awaaz Voice — Hindi / Telugu</h1>
<div class="sub">Speak (or type) — the pipeline transcribes, replies, and speaks. First turn takes ~1-2 min (warm-up), then ~8 s per turn.</div>
<div class="lang"><button id="hi" class="on" onclick="setLang('hi')">हिंदी</button><button id="te" onclick="setLang('te')">తెలుగు</button></div>
<button class="mic" id="mic" onclick="toggleMic()">🎤 Tap to speak</button>
<div class="row"><input id="text" placeholder="...or type here" autocomplete="off"><button class="send" onclick="sendText()">Speak this</button></div>
<div id="status"></div>
<div id="out"></div>
<script>
const API = "https://raj315920--voice-pipeline-voice-turn.modal.run";
let lang = "hi", recording = false, bufs = [], proc = null, ctx = null, stream = null;
function setLang(l) { lang = l;
  document.getElementById("hi").className = l === "hi" ? "on" : "";
  document.getElementById("te").className = l === "te" ? "on" : ""; }
function status(t) { document.getElementById("status").textContent = t; }
function toggleMic() {
  if (recording) { stopMic(); } else { startMic(); }
}
async function startMic() {
  try { stream = await navigator.mediaDevices.getUserMedia({audio: true}); }
  catch (e) { status("Mic permission denied. Use the text box instead."); return; }
  ctx = new (window.AudioContext || window.webkitAudioContext)({sampleRate: 16000});
  proc = ctx.createScriptProcessor(4096, 1, 1);
  ctx.createMediaStreamSource(stream).connect(proc);
  proc.connect(ctx.destination);
  bufs = [];
  proc.onaudioprocess = e => bufs.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  recording = true;
  const b = document.getElementById("mic"); b.className = "mic rec"; b.textContent = "⏹ Stop & send";
  status("Recording... speak now");
}
function stopMic() {
  recording = false;
  proc.disconnect(); stream.getTracks().forEach(t => t.stop()); ctx.close();
  const b = document.getElementById("mic"); b.className = "mic"; b.textContent = "🎤 Tap to speak";
  let n = 0; bufs.forEach(x => n += x.length);
  const all = new Float32Array(n); let o = 0;
  bufs.forEach(x => { all.set(x, o); o += x.length; });
  const ratio = ctx.sampleRate / 16000;
  const len = Math.floor(all.length / ratio);
  const out = new Float32Array(len);
  for (let i = 0; i < len; i++) {
    let s = 0; for (let j = 0; j < ratio; j++) s += all[Math.floor(i * ratio) + j] || 0;
    out[i] = s / ratio;
  }
  const wav = new Int16Array(len);
  for (let i = 0; i < len; i++) wav[i] = Math.max(-1, Math.min(1, out[i])) * 32767;
  const hdr = new ArrayBuffer(44), v = new DataView(hdr);
  const ws = (off, s) => { for (let i = 0; i < s.length; i++) v.setUint8(off + i, s.charCodeAt(i)); };
  ws(0, "RIFF"); v.setUint32(4, 36 + len * 2, true); ws(8, "WAVE"); ws(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, 16000, true); v.setUint32(28, 32000, true); v.setUint16(32, 2, true);
  v.setUint16(34, 16, true); ws(36, "data"); v.setUint32(40, len * 2, true);
  const blob = new Uint8Array(44 + len * 2);
  blob.set(new Uint8Array(hdr), 0); blob.set(new Uint8Array(wav.buffer), 44);
  let bin = "";
  for (let i = 0; i < blob.length; i += 8192) {
    bin += String.fromCharCode(...blob.subarray(i, i + 8192));
  }
  sendTurn(btoa(bin));
}
function sendText() {
  const t = document.getElementById("text").value.trim();
  if (t) sendTurn(null, t);
}
async function sendTurn(wavB64, text) {
  status("Processing... transcribe → think → speak (≈8 s)");
  const body = { lang: lang };
  if (wavB64) body.wav_b64 = wavB64; if (text) body.text = text;
  try {
    const r = await fetch(API, { method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body) });
    const j = await r.json();
    if (j.error) { status("Error: " + j.error); return; }
    document.getElementById("out").innerHTML =
      '<div class="card"><div class="lbl">Heard</div><div class="txt">' + escapeHtml(j.heard) +
      '</div><div class="chips"><span class="chip">ASR ' + j.asr_ms + ' ms</span></div></div>' +
      '<div class="card"><div class="lbl">Replied</div><div class="txt">' + escapeHtml(j.reply) +
      '</div><div class="chips"><span class="chip">LLM ' + j.llm_ms + ' ms</span><span class="chip">TTS ' + j.tts_ms + ' ms</span></div>' +
      '<audio controls src="data:audio/wav;base64,' + j.audio_b64 + '"></audio></div>';
    status("Done. Play the reply.");
  } catch (e) { status("Error: " + e); }
}
function escapeHtml(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
document.getElementById("text").addEventListener("keydown", e => { if (e.key === "Enter") sendText(); });
</script>
</div></body></html>"""
VOL_Q = "/root/qwen3-a1"
VOL_I = "/root/indicvoices"
vol_q = modal.Volume.from_name("qwen3-a1")
vol_i = modal.Volume.from_name("indicvoices")
EVAL_DIR = f"{VOL_I}/voice_eval"
TRAIN_MANIFEST = f"{EVAL_DIR}/train_manifest.jsonl"
EVAL_MANIFEST = f"{EVAL_DIR}/eval_manifest.jsonl"
FEATS_DIR = f"{VOL_Q}/voice_feats/whisper-16k"
FEAT_SHARD = 2000
WHISPER_TUNED = f"{VOL_Q}/models/whisper-small-hi-te-v2"
WHISPER_SMALL = "openai/whisper-small"
WHISPER_MEDIUM = "openai/whisper-medium"
PARLER = "ai4bharat/indic-parler-tts"
HINDI_ROOT = "kagglehub/datasets/neh1277/indicvoices-hindi-1/versions/1"
TELUGU_ROOT = "hf/IndicVoices/telugu"


def model_dir(repo_id):
    return f"{VOL_Q}/models/{repo_id}"


def iter_rows(roots, lang_of_root):
    """Yield (lang, text, flac_bytes, duration) from parquet shards on the volume."""
    import glob
    import os

    import pyarrow.parquet as pq

    for root in roots:
        base = os.path.join(VOL_I, root)
        shards = sorted(glob.glob(os.path.join(base, "**", "*.parquet"), recursive=True))
        for shard in shards:
            table = pq.read_table(shard, columns=["text", "lang", "duration", "audio_filepath", "scenario"])
            for rec in table.to_pylist():
                if rec["scenario"] != "Conversation":
                    continue
                audio = rec.get("audio_filepath") or {}
                blob = audio.get("bytes") if isinstance(audio, dict) else None
                if not blob:
                    continue
                yield rec["lang"] or lang_of_root, rec["text"].strip(), blob, rec["duration"]


def write_wav(blob, path):
    import io

    import numpy as np
    import soundfile as sf

    data, sr = sf.read(io.BytesIO(blob), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    sf.write(path, data, sr)


def normalize(text):
    import re

    text = re.sub(r"[।,.!?;:\'\"()\[\]।॥]", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def featurize_rows(rows, processor, tokenizer, decoder_start_id, tag):
    """Shared featurize path: log-mel + language-prefixed labels, 448-token cap.

    Runs on CPU (slow, cheap) or GPU box (fast, billed) — same bytes either way.
    """
    import soundfile as _sf

    out, skipped = [], 0
    for i, r in enumerate(rows):
        if i and i % 2000 == 0:
            print(f"LOAD_PROGRESS {tag} {i}/{len(rows)}", flush=True)
        audio, sr = _sf.read(r["path"], dtype="float32")
        feat = processor.feature_extractor(audio, sampling_rate=sr)["input_features"][0]
        tokenizer.set_prefix_tokens(language="hindi" if r["lang"] == "hi" else "telugu",
                                    task="transcribe")
        raw_ids = tokenizer(r["text"]).input_ids
        if len(raw_ids) > 448:
            skipped += 1
            continue
        labels = raw_ids[1:] if raw_ids and raw_ids[0] == decoder_start_id else raw_ids
        out.append({"input_features": feat, "labels": labels, "text": r["text"],
                    "lang": r["lang"], "dur": r["dur"]})
    print(f"LOAD_SPLIT {tag} kept={len(out)} skipped_long={skipped}")
    return out


@app.function(image=image, secrets=[modal.Secret.from_name("hf-indicvoices", required_keys=["HF_TOKEN"])],
               timeout=900)
def probe_tts():
    import os

    from huggingface_hub import hf_hub_download
    path = hf_hub_download(PARLER, "README.md", token=os.environ["HF_TOKEN"], local_dir="/tmp/ttscard")
    card = open(path, encoding="utf-8").read()
    start = card.find("import torch")
    print("CARD_USAGE_BLOCK:")
    print(card[max(0, start - 200):start + 2200])


@app.function(image=image, secrets=[modal.Secret.from_name("hf-indicvoices", required_keys=["HF_TOKEN"])],
              volumes={VOL_Q: vol_q, VOL_I: vol_i}, timeout=3600)
def cache_models():
    import os

    from huggingface_hub import snapshot_download

    token = os.environ["HF_TOKEN"]
    for repo in (WHISPER_SMALL, WHISPER_MEDIUM, PARLER):
        snapshot_download(repo, local_dir=model_dir(repo), token=token)
        print(f"CACHED {repo}")
    vol_q.commit()


@app.function(image=image, volumes={VOL_I: vol_i}, timeout=3600)
def prep(n_eval_per_lang: int = 100, n_train_per_lang: int = 8000):
    import os

    os.makedirs(EVAL_DIR, exist_ok=True)
    eval_rows, train_rows = [], []
    counts = {"hi_eval": 0, "te_eval": 0, "hi_train": 0, "te_train": 0}
    for lang, text, blob, dur in iter_rows((HINDI_ROOT, TELUGU_ROOT), {"hi": "hi", "te": "te"}):
        if not (2.0 <= dur <= 10.0) or len(text) < 5:
            continue
        row = {"lang": lang, "text": text, "dur": dur}
        if lang == "hi" and counts["hi_eval"] < n_eval_per_lang:
            row["path"] = f"{EVAL_DIR}/hi_eval_{counts['hi_eval']}.wav"
            write_wav(blob, row["path"])
            eval_rows.append(row)
            counts["hi_eval"] += 1
        elif lang == "te" and counts["te_eval"] < n_eval_per_lang:
            row["path"] = f"{EVAL_DIR}/te_eval_{counts['te_eval']}.wav"
            write_wav(blob, row["path"])
            eval_rows.append(row)
            counts["te_eval"] += 1
        elif lang == "hi" and counts["hi_train"] < n_train_per_lang:
            row["path"] = f"{EVAL_DIR}/hi_train_{counts['hi_train']}.wav"
            write_wav(blob, row["path"])
            train_rows.append(row)
            counts["hi_train"] += 1
        elif lang == "te" and counts["te_train"] < n_train_per_lang:
            row["path"] = f"{EVAL_DIR}/te_train_{counts['te_train']}.wav"
            write_wav(blob, row["path"])
            train_rows.append(row)
            counts["te_train"] += 1
        if all(counts[k] >= v for k, v in
               {"hi_eval": n_eval_per_lang, "te_eval": n_eval_per_lang,
                "hi_train": n_train_per_lang, "te_train": n_train_per_lang}.items()):
            break
    for path, rows in ((EVAL_MANIFEST, eval_rows), (TRAIN_MANIFEST, train_rows)):
        with open(path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"PREP_DONE {json.dumps(counts)}")
    vol_i.commit()


@app.function(gpu="H100", image=image, volumes={VOL_Q: vol_q, VOL_I: vol_i}, timeout=3600)
def asr_eval():
    import json
    import time

    import soundfile as sf
    from jiwer import wer as jiwer_wer
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    rows = [json.loads(l) for l in open(EVAL_MANIFEST, encoding="utf-8")]
    rows = [r for r in rows if len(normalize(r["text"]).split()) >= 3]
    print(f"ASR_EVAL_CLIPS kept={len(rows)}/200 (content utterances >=3 words; backchannels excluded)")
    results = {}
    models = [("medium", model_dir(WHISPER_MEDIUM)), ("small", model_dir(WHISPER_SMALL)),
              ("v1", f"{VOL_Q}/models/whisper-small-hi-te"),
              ("v2", f"{VOL_Q}/models/whisper-small-hi-te-v2")]
    for tag, path in models:
        model = WhisperForConditionalGeneration.from_pretrained(
            path, torch_dtype="float32").to("cuda").eval()
        processor = WhisperProcessor.from_pretrained(path)
        hyps = {"hi": [], "te": []}
        refs = {"hi": [], "te": []}
        t0 = time.perf_counter()
        for r in rows:
            audio, sr = sf.read(r["path"], dtype="float32")
            inputs = processor(audio, sampling_rate=sr, return_tensors="pt").input_features.to("cuda")
            lang = "hindi" if r["lang"] == "hi" else "telugu"
            max_toks = min(440, int(r["dur"] * 40) + 60)
            import torch
            with torch.no_grad():
                out = model.generate(inputs, language=lang, task="transcribe", max_new_tokens=max_toks)
            text = processor.batch_decode(out, skip_special_tokens=True)[0]
            hyps[r["lang"]].append(normalize(text))
            refs[r["lang"]].append(normalize(r["text"]))
        elapsed = time.perf_counter() - t0
        results[tag] = {
            "hi_wer": round(jiwer_wer(refs["hi"], hyps["hi"]) * 100, 2),
            "te_wer": round(jiwer_wer(refs["te"], hyps["te"]) * 100, 2),
            "sec_per_clip": round(elapsed / len(rows), 3),
        }
        print(f"ASR_BASELINE {tag} " + json.dumps(results[tag]))
        del model
        import torch
        torch.cuda.empty_cache()
    print("ASR_BASELINE_RESULT " + json.dumps(results))
    with open(f"{EVAL_DIR}/bench_asr.json", "w", encoding="utf-8") as fh:
        json.dump({"clips": len(rows), "models": results}, fh, ensure_ascii=False)
    vol_i.commit()
    print("BENCH_ASR_SAVED voice_eval/bench_asr.json")


@app.function(image=image, volumes={VOL_Q: vol_q, VOL_I: vol_i}, timeout=7200, memory=32768)
def featurize_whisper(train_cap: int = 0):
    """CPU precompute for the scale-up: featurize is CPU-bound, so doing it on a
    billed H100 burned ~$2.6 of silence last round. Same bytes, ~$0.05 here."""
    import json
    import os
    import random

    import torch
    from transformers import WhisperConfig, WhisperProcessor

    processor = WhisperProcessor.from_pretrained(model_dir(WHISPER_SMALL))
    decoder_start = WhisperConfig.from_pretrained(model_dir(WHISPER_SMALL)).decoder_start_token_id

    def load_rows(manifest):
        return [json.loads(l) for l in open(manifest, encoding="utf-8")]

    os.makedirs(FEATS_DIR, exist_ok=True)
    existing = set(os.listdir(FEATS_DIR))
    train_rows = load_rows(TRAIN_MANIFEST)
    if train_cap > 0:
        random.seed(20260828)
        hi = [r for r in train_rows if r["lang"] == "hi"][:train_cap // 2]
        te = [r for r in train_rows if r["lang"] == "te"][:train_cap // 2]
        train_rows = hi + te
        random.shuffle(train_rows)
    for i in range(0, len(train_rows), FEAT_SHARD):
        name = f"train-{i // FEAT_SHARD:02d}.pt"
        if train_cap == 0 and name in existing:
            print(f"FEAT_SHARD_SKIP {i // FEAT_SHARD} (already committed)", flush=True)
            continue
        shard = featurize_rows(train_rows[i:i + FEAT_SHARD], processor, processor.tokenizer,
                               decoder_start, f"train-{i // FEAT_SHARD}")
        torch.save(shard, f"{FEATS_DIR}/{name}")
        vol_q.commit()
        print(f"FEAT_SHARD_SAVED {i // FEAT_SHARD}", flush=True)
    if "eval.pt" in existing:
        print("FEAT_EVAL_SKIP (already committed)", flush=True)
    else:
        eval_rows = load_rows(EVAL_MANIFEST)
        torch.save(featurize_rows(eval_rows, processor, processor.tokenizer,
                                  decoder_start, "eval"), f"{FEATS_DIR}/eval.pt")
        vol_q.commit()
    vol_q.commit()
    print(f"FEATS_DONE dir={FEATS_DIR} train={len(train_rows)} eval={len(eval_rows)}")


@app.function(gpu="H100", image=image, volumes={VOL_Q: vol_q, VOL_I: vol_i}, timeout=7200, memory=16384)
def asr_finetune(steps: int = 500, batch_size: int = 8, save_name: str = "whisper-small-hi-te"):
    import glob
    import json

    import torch
    from jiwer import wer as jiwer_wer
    from transformers import (Seq2SeqTrainer, Seq2SeqTrainingArguments, WhisperForConditionalGeneration,
                              WhisperProcessor)

    processor = WhisperProcessor.from_pretrained(model_dir(WHISPER_SMALL))
    model = WhisperForConditionalGeneration.from_pretrained(
        model_dir(WHISPER_SMALL)).to("cuda")

    train_set = []
    for path in sorted(glob.glob(f"{FEATS_DIR}/train-*.pt")):
        train_set.extend(torch.load(path, weights_only=False))
    eval_set = torch.load(f"{FEATS_DIR}/eval.pt", weights_only=False)
    print(f"FT_DATA train={len(train_set)} eval={len(eval_set)} (precomputed feats, no GPU featurize)")

    def collate(batch):
        feats = torch.stack([torch.as_tensor(b["input_features"]) for b in batch])
        longest = max(len(b["labels"]) for b in batch)
        labels = [b["labels"] + [-100] * (longest - len(b["labels"])) for b in batch]
        return {"input_features": feats, "labels": torch.tensor(labels)}

    args = Seq2SeqTrainingArguments(
        output_dir="/tmp/whisper-ft", max_steps=steps, per_device_train_batch_size=batch_size,
        learning_rate=1e-5, logging_steps=100, save_strategy="no", bf16=True, warmup_steps=100,
        predict_with_generate=True, report_to="none", seed=20260828,
    )
    trainer = Seq2SeqTrainer(model=model, args=args, train_dataset=train_set, data_collator=collate)
    trainer.train()

    def eval_wer():
        model.eval()
        hyps, refs = {"hi": [], "te": []}, {"hi": [], "te": []}
        with torch.no_grad():
            for r in eval_set:
                if len(normalize(r["text"]).split()) < 3:
                    continue
                feats = torch.tensor([r["input_features"]]).to("cuda")
                lang = "hindi" if r["lang"] == "hi" else "telugu"
                max_toks = min(440, int(r["dur"] * 40) + 60)
                out = model.generate(feats, language=lang, task="transcribe", max_new_tokens=max_toks)
                text = processor.batch_decode(out, skip_special_tokens=True)[0]
                hyps[r["lang"]].append(normalize(text))
                refs[r["lang"]].append(normalize(r["text"]))
        return {"hi_wer": round(jiwer_wer(refs["hi"], hyps["hi"]) * 100, 2),
                "te_wer": round(jiwer_wer(refs["te"], hyps["te"]) * 100, 2)}

    result = eval_wer()
    print("ASR_TUNED " + json.dumps(result))
    out_dir = f"{VOL_Q}/models/{save_name}"
    model.save_pretrained(out_dir)
    processor.save_pretrained(out_dir)
    vol_q.commit()
    print(f"ASR_TUNED_SAVED {out_dir} " + json.dumps(result))


@app.function(gpu="H100", image=tts_image, volumes={VOL_Q: vol_q}, timeout=1800, scaledown_window=600)
def tts_gen(text: str):
    import time

    import torch
    from parler_tts import ParlerTTSForConditionalGeneration
    from transformers import AutoTokenizer

    if "model" not in _TTS_STATE:
        model = ParlerTTSForConditionalGeneration.from_pretrained(
            model_dir(PARLER), torch_dtype=torch.bfloat16).to("cuda").eval()
        tok = AutoTokenizer.from_pretrained(model_dir(PARLER))
        desc_tok = AutoTokenizer.from_pretrained(model.config.text_encoder._name_or_path)
        _TTS_STATE.update(model=model, tok=tok, desc_tok=desc_tok, sr=model.config.sampling_rate)
        d = desc_tok(TTS_DESC, return_tensors="pt").to("cuda")
        p = tok(text[:40], return_tensors="pt").to("cuda")
        with torch.no_grad():
            model.generate(input_ids=d.input_ids, attention_mask=d.attention_mask,
                           prompt_input_ids=p.input_ids, prompt_attention_mask=p.attention_mask)
        print("TTS_MODEL_LOADED")
    model, tok, desc_tok, sr = (_TTS_STATE["model"], _TTS_STATE["tok"],
                                _TTS_STATE["desc_tok"], _TTS_STATE["sr"])
    d = desc_tok(TTS_DESC, return_tensors="pt").to("cuda")
    p = tok(text[:220], return_tensors="pt").to("cuda")
    t0 = time.perf_counter()
    with torch.no_grad():
        audio = model.generate(input_ids=d.input_ids, attention_mask=d.attention_mask,
                               prompt_input_ids=p.input_ids, prompt_attention_mask=p.attention_mask)
    synth_sec = time.perf_counter() - t0
    data = audio.float().cpu().numpy().squeeze()
    return data, synth_sec, sr


@app.function(image=image, volumes={VOL_I: vol_i}, timeout=3600)
def tts_demo():
    import json

    import soundfile as sf

    sentences = [
        ("hi", "नमस्ते जी, बताइए आपको क्या मदद चाहिए।"),
        ("hi", "आपकी बात ध्यान से सुन रहे हैं, आप आगे बोलिए।"),
        ("te", "నమస్కారం, మీకు ఏవైనా సహాయం కావాలా చెప్పండి."),
        ("te", "మీ మాట శ్రద్ధగా వినుతున్నాను, మీరు కొనసాగించండి."),
    ]
    print("warming TTS container (first call loads the model)...")
    tts_gen.remote("warmup")
    results = []
    for lang, text in sentences:
        data, synth_sec, sr = tts_gen.remote(text)
        path = f"{EVAL_DIR}/tts_{lang}_{len(results)}.wav"
        sf.write(path, data, sr)
        results.append({"lang": lang, "text": text, "synthesize_sec": round(synth_sec, 2),
                        "audio_sec": round(len(data) / sr, 2), "path": path, "sampling_rate": sr})
        print(f"TTS {lang} synth={synth_sec:.2f}s audio={len(data)/sr:.2f}s :: {text[:40]}")
    vol_i.commit()
    print("TTS_RESULT " + json.dumps(results, ensure_ascii=False))


@app.function(gpu="H100", image=image, volumes={VOL_Q: vol_q, VOL_I: vol_i}, timeout=3600)
def voice_loop():
    import json
    import os
    import time

    import soundfile as sf
    import torch
    from peft import PeftModel
    from transformers import (AutoModelForCausalLM, AutoTokenizer, WhisperForConditionalGeneration,
                              WhisperProcessor)

    torch.manual_seed(20260828)
    rows = [json.loads(l) for l in open(EVAL_MANIFEST, encoding="utf-8") if "hi_eval_0" in l or "te_eval_0" in l]
    if len(rows) < 2:
        rows = [json.loads(l) for l in open(EVAL_MANIFEST, encoding="utf-8")][:2]

    whisper = WhisperForConditionalGeneration.from_pretrained(
        WHISPER_TUNED).to("cuda").eval()
    wproc = WhisperProcessor.from_pretrained(WHISPER_TUNED)

    llm_tok = AutoTokenizer.from_pretrained(f"{VOL_Q}/models/Qwen/Qwen3-1.7B-Base")
    if llm_tok.pad_token is None:
        llm_tok.pad_token = llm_tok.eos_token
    base = AutoModelForCausalLM.from_pretrained(
        f"{VOL_Q}/models/Qwen/Qwen3-1.7B-Base", torch_dtype=torch.bfloat16)
    llm = PeftModel.from_pretrained(base, f"{VOL_Q}/adapter_a2").to("cuda").eval()

    print("warming TTS container...")
    tts_gen.remote("warmup")

    results = []
    for r in rows:
        audio, sr = sf.read(r["path"], dtype="float32")
        feats = wproc(audio, sampling_rate=sr, return_tensors="pt").input_features.to("cuda")
        lang_name = "hindi" if r["lang"] == "hi" else "telugu"
        t0 = time.perf_counter()
        with torch.no_grad():
            out = whisper.generate(feats, language=lang_name, task="transcribe",
                                   max_new_tokens=min(440, int(r["dur"] * 40) + 60))
        t_asr = (time.perf_counter() - t0) * 1000
        heard = wproc.batch_decode(out, skip_special_tokens=True)[0]

        prompt = llm_tok.apply_chat_template([{"role": "user", "content": heard}],
                                             add_generation_prompt=True, return_tensors="pt").to("cuda")
        t0 = time.perf_counter()
        with torch.no_grad():
            gen = llm.generate(prompt, max_new_tokens=24, do_sample=True, temperature=0.8,
                               top_p=0.95, pad_token_id=llm_tok.pad_token_id,
                               eos_token_id=[llm_tok.convert_tokens_to_ids("<|im_end|>"),
                                             llm_tok.eos_token_id])
        t_llm = (time.perf_counter() - t0) * 1000
        reply = llm_tok.decode(gen[0, prompt.shape[1]:], skip_special_tokens=True)

        t0 = time.perf_counter()
        data, _, sr = tts_gen.remote(reply[:220])
        t_tts = (time.perf_counter() - t0) * 1000
        path = f"{EVAL_DIR}/loop_{r['lang']}.wav"
        sf.write(path, data, sr)

        results.append({"lang": r["lang"], "gold": r["text"], "heard": heard, "reply": reply,
                        "asr_ms": round(t_asr), "llm_ms_24tok": round(t_llm),
                        "tts_ms": round(t_tts), "audio_path": path})
        print(f"LOOP {r['lang']} asr={t_asr:.0f}ms llm(24tok)={t_llm:.0f}ms tts={t_tts:.0f}ms")
        print(f"  HEARD: {heard[:70]}")
        print(f"  REPLY: {reply[:70]}")
    vol_i.commit()
    print("VOICE_LOOP_RESULT " + json.dumps(results, ensure_ascii=False))


@app.function(gpu="H100", image=image, volumes={VOL_Q: vol_q, VOL_I: vol_i}, timeout=1800)
def asr_debug(n: int = 3):
    import json

    import soundfile as sf
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    model = WhisperForConditionalGeneration.from_pretrained(
        model_dir(WHISPER_MEDIUM), torch_dtype="float32").to("cuda").eval()
    processor = WhisperProcessor.from_pretrained(model_dir(WHISPER_MEDIUM))
    rows = [json.loads(l) for l in open(EVAL_MANIFEST, encoding="utf-8")]
    for r in [x for x in rows if x["lang"] == "hi"][:n] + [x for x in rows if x["lang"] == "te"][:n]:
        data, sr = sf.read(r["path"], dtype="float32")
        print(f"CLIP {r['path'].split('/')[-1]} sr={sr} samples={len(data)} dur={r['dur']}")
        print(f"  REF: {r['text'][:90]}")
        for kw in ({"language": "hindi" if r["lang"] == "hi" else "telugu", "task": "transcribe"}, {}):
            feats = processor(data, sampling_rate=sr, return_tensors="pt").input_features.to("cuda")
            with torch.no_grad():
                out = model.generate(feats, max_new_tokens=120, **kw)
            text = processor.batch_decode(out, skip_special_tokens=True)[0]
            print(f"  HYP{list(kw.values()) or 'auto'}: {text[:90]}")


@app.function(image=tts_image, timeout=600)
def tts_image_probe():
    import glob
    import os

    import torch
    print("TORCH", torch.__version__, "| cuda build:", torch.version.cuda)
    import site
    for sp in site.getsitepackages():
        hits = glob.glob(os.path.join(sp, "nvidia", "*", "lib", "libcudart*"))
        if hits:
            print("LIBCUDART:", [h.split("nvidia/")[-1] for h in hits])
    pkgs = os.popen("pip list 2>/dev/null | grep -i -E \"nvidia|torch\"").read()
    print(pkgs)
    try:
        from parler_tts import ParlerTTSForConditionalGeneration
        print("PARLER_IMPORT OK")
    except Exception as e:
        print("PARLER_IMPORT FAIL:", str(e)[:200])


@app.function(image=image)
@modal.fastapi_endpoint(method="GET")
def voice_ui():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(VOICE_UI_HTML)


@app.function(gpu="H100", image=image, volumes={VOL_Q: vol_q, VOL_I: vol_i}, scaledown_window=180, timeout=600)
@modal.fastapi_endpoint(method="POST")
def voice_turn(payload: dict):
    import base64
    import io
    import time

    import soundfile as sf
    import torch
    from peft import PeftModel
    from transformers import (AutoModelForCausalLM, AutoTokenizer, WhisperForConditionalGeneration,
                              WhisperProcessor)

    if "whisper" not in _VOICE_STATE:
        whisper = WhisperForConditionalGeneration.from_pretrained(
            WHISPER_TUNED).to("cuda").eval()
        wproc = WhisperProcessor.from_pretrained(WHISPER_TUNED)
        ltok = AutoTokenizer.from_pretrained(f"{VOL_Q}/models/Qwen/Qwen3-1.7B-Base")
        if ltok.pad_token is None:
            ltok.pad_token = ltok.eos_token
        base = AutoModelForCausalLM.from_pretrained(
            f"{VOL_Q}/models/Qwen/Qwen3-1.7B-Base", torch_dtype=torch.bfloat16)
        llm = PeftModel.from_pretrained(base, f"{VOL_Q}/adapter_a2").to("cuda").eval()
        _VOICE_STATE.update(whisper=whisper, wproc=wproc, llm=llm, ltok=ltok)

    whisper = _VOICE_STATE["whisper"]
    wproc = _VOICE_STATE["wproc"]
    llm = _VOICE_STATE["llm"]
    ltok = _VOICE_STATE["ltok"]

    if payload.get("text"):
        heard = payload["text"].strip()
        asr_ms = 0
    elif payload.get("wav_b64"):
        data, sr = sf.read(io.BytesIO(base64.b64decode(payload["wav_b64"])), dtype="float32")
        lang = "hindi" if payload.get("lang", "hi") == "hi" else "telugu"
        t0 = time.perf_counter()
        feats = wproc(data, sampling_rate=sr, return_tensors="pt").input_features.to("cuda")
        with torch.no_grad():
            out = whisper.generate(feats, language=lang, task="transcribe",
                                   max_new_tokens=min(440, int(len(data) / sr * 40) + 60))
        asr_ms = (time.perf_counter() - t0) * 1000
        heard = wproc.batch_decode(out, skip_special_tokens=True)[0].strip()
    else:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="send wav_b64 or text")

    prompt = ltok.apply_chat_template([{"role": "user", "content": heard}],
                                      add_generation_prompt=True, return_tensors="pt").to("cuda")
    t0 = time.perf_counter()
    with torch.no_grad():
        gen = llm.generate(prompt, max_new_tokens=40, do_sample=True, temperature=0.8,
                           top_p=0.95, pad_token_id=ltok.pad_token_id,
                           eos_token_id=[ltok.convert_tokens_to_ids("<|im_end|>"),
                                         ltok.eos_token_id])
    llm_ms = (time.perf_counter() - t0) * 1000
    reply = ltok.decode(gen[0, prompt.shape[1]:], skip_special_tokens=True).strip()
    cut = max(reply.rfind("।"), reply.rfind("."), reply.rfind("?"), reply.rfind("!"))
    if cut > 10:
        reply = reply[:cut + 1].strip()

    t0 = time.perf_counter()
    audio, _, sr_tts = tts_gen.remote(reply[:220])
    tts_ms = (time.perf_counter() - t0) * 1000

    buf = io.BytesIO()
    sf.write(buf, audio, sr_tts, format="WAV")
    return {"heard": heard, "reply": reply, "asr_ms": round(asr_ms), "llm_ms": round(llm_ms),
            "tts_ms": round(tts_ms), "audio_b64": base64.b64encode(buf.getvalue()).decode()}


@app.function(gpu="H100", image=image, volumes={VOL_Q: vol_q}, scaledown_window=600, timeout=300)
@modal.fastapi_endpoint(method="POST")
def asr_turn(payload: dict):
    """Stage-split endpoint: transcribe only (ours whisper-small-hi-te-v2).

    Lets the Go gateway pair our STT with any LLM (hybrid voice modes).
    """
    import base64
    import io
    import time

    import soundfile as sf
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    if "whisper" not in _VOICE_STATE:
        _VOICE_STATE["whisper"] = WhisperForConditionalGeneration.from_pretrained(
            WHISPER_TUNED).to("cuda").eval()
        _VOICE_STATE["wproc"] = WhisperProcessor.from_pretrained(WHISPER_TUNED)

    if payload.get("text"):
        return {"heard": payload["text"].strip(), "asr_ms": 0}
    if not payload.get("wav_b64"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="send wav_b64 or text")

    data, sr = sf.read(io.BytesIO(base64.b64decode(payload["wav_b64"])), dtype="float32")
    lang = payload.get("lang", "auto")
    # "auto" lets whisper detect the language itself — forcing "hindi" on
    # Telugu speech garbles the transcript and the whole turn goes Hindi.
    kw = {} if lang == "auto" else {"language": "hindi" if lang == "hi" else "telugu"}
    t0 = time.perf_counter()
    feats = _VOICE_STATE["wproc"](data, sampling_rate=sr,
                                  return_tensors="pt").input_features.to("cuda")
    with torch.no_grad():
        out = _VOICE_STATE["whisper"].generate(
            feats, task="transcribe",
            max_new_tokens=min(440, int(len(data) / sr * 40) + 60), **kw)
    asr_ms = (time.perf_counter() - t0) * 1000
    heard = _VOICE_STATE["wproc"].batch_decode(out, skip_special_tokens=True)[0].strip()
    return {"heard": heard, "asr_ms": round(asr_ms)}


@app.function(image=image, scaledown_window=600, timeout=300)
@modal.fastapi_endpoint(method="POST")
def tts_turn(payload: dict):
    """Stage-split endpoint: synthesize only (indic-parler-tts). CPU proxy —
    the GPU work happens in tts_gen, so this container never bills H100."""
    import base64
    import io
    import time

    import soundfile as sf

    text = (payload.get("text") or "").strip()
    if not text:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="send text")
    t0 = time.perf_counter()
    audio, _, sr = tts_gen.remote(text[:220])
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV")
    return {"audio_b64": base64.b64encode(buf.getvalue()).decode(),
            "tts_ms": round((time.perf_counter() - t0) * 1000)}


@app.function(image=image, volumes={VOL_Q: vol_q}, timeout=3600, memory=8192)
def inspect_asr():
    import glob
    import os

    from safetensors.torch import load_file

    base_dir = model_dir(WHISPER_SMALL)
    tuned_dirs = sorted(glob.glob(f"{VOL_Q}/models/whisper-small-hi-te*"))
    for d in [base_dir] + tuned_dirs:
        files = sorted(f for f in os.listdir(d))
        total = sum(os.path.getsize(os.path.join(d, f)) for f in files)
        print(f"DIR {d.split('/')[-1]} files={len(files)} total={total / 1e9:.2f}GB")
    bfile = next(f for f in os.listdir(base_dir) if f.endswith((".safetensors", ".bin")))
    b = load_file(os.path.join(base_dir, bfile))
    for tuned_dir in tuned_dirs:
        tfile = next(f for f in os.listdir(tuned_dir) if f.endswith((".safetensors", ".bin")))
        t = load_file(os.path.join(tuned_dir, tfile))
        tag = tuned_dir.split("/")[-1]
        params = sum(x.numel() for x in t.values())
        print(f"TENSORS {tag} base={len(b)} tuned={len(t)} tuned_params={params}")
        nan = sum(int(x.isnan().sum()) + int(x.isinf().sum()) for x in t.values())
        deltas, enc_d, dec_d = [], [], []
        for k in t:
            if k not in b or t[k].shape != b[k].shape:
                continue
            d = (t[k].float() - b[k].float()).abs()
            m = float(d.mean())
            deltas.append(m)
            (enc_d if "encoder" in k else dec_d).append(m)
        print(f"NaN_Inf_{tag}={nan}")
        print(f"mean_abs_delta_{tag} all={sum(deltas)/len(deltas):.2e} "
              f"encoder={sum(enc_d)/len(enc_d):.2e} decoder={sum(dec_d)/len(dec_d):.2e}")


@app.function(image=image, volumes={VOL_Q: vol_q, VOL_I: vol_i}, timeout=1800)
def probe_telugu_tokens(n: int = 3000):
    import json
    import os

    import numpy as np
    from transformers import WhisperProcessor

    processor = WhisperProcessor.from_pretrained(model_dir(WHISPER_SMALL))
    tokenizer = processor.tokenizer
    for fname, lang in (("indicvoices_hindi_transcripts.jsonl", "hi"),
                        ("indicvoices_telugu_transcripts.jsonl", "te")):
        lengths = []
        path = os.path.join(VOL_I, "extracted", fname)
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= n:
                    break
                rec = json.loads(line)
                if rec["scenario"] != "Conversation":
                    continue
                labels = tokenizer(rec["text"], truncation=True, max_length=200).input_ids
                raw_len = len(tokenizer(rec["text"]).input_ids)
                lengths.append((raw_len, len(labels)))
        arr = np.array([r for r, _ in lengths])
        trunc = sum(1 for r, t in lengths if r > 200)
        over120 = sum(1 for r, _ in lengths if r > 120)
        print(f"TOKENS {lang} n={len(lengths)} max={arr.max()} mean={arr.mean():.1f} "
              f"p99={np.percentile(arr, 99):.0f} rows_truncated_at_200={trunc} rows_over_120={over120}")


@app.local_entrypoint()
def main(step: str = "prep", whisper_steps: int = 500, whisper_train_cap: int = 0,
         whisper_save: str = "whisper-small-hi-te"):
    if step == "probe-tokens":
        probe_telugu_tokens.remote()
    elif step == "inspect-asr":
        inspect_asr.remote()
    elif step == "tts-probe":
        tts_image_probe.remote()
    elif step == "asr-debug":
        asr_debug.remote()
    elif step == "probe-tts":
        probe_tts.remote()
    elif step == "cache":
        cache_models.remote()
    elif step == "prep":
        prep.remote()
    elif step == "asr-eval":
        asr_eval.remote()
    elif step == "featurize-whisper":
        featurize_whisper.remote(train_cap=whisper_train_cap)
    elif step == "asr-finetune":
        asr_finetune.remote(steps=whisper_steps, save_name=whisper_save)
    elif step == "tts-demo":
        tts_demo.remote()
    elif step == "loop":
        voice_loop.remote()
    else:
        raise SystemExit(f"unknown step: {step}")
