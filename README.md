# Awaaz

Voice and chat AI that speaks Hindi and Telugu for real. Not translated English in a Hindi mask: every training sentence was written or spoken by a native speaker, and the numbers below are measured, low where they are low.

Live: https://awaaz-psi.vercel.app (API: https://awaaz-w56x.onrender.com)

## What it is

One rule runs the whole project: only native-authored Hindi/Telugu data counts. No machine translation, no made-up labels, no unverified consent. I threw out easy datasets four times for breaking this, including a 383k-clip Hindi set with no license and anything translated.

From that rule came four pieces:

Data. 83,196 records from 8 pinned sources: BHAAV Hindi stories, IIIT-H Telugu sentences, MaSaC Hinglish dialogue, M2H2 humor dialogue in Devanagari, CMU Hinglish chats, Sowmith Telugu speech, plus 610k real IndicVoices utterances for training. Everything checksummed in `data/DATA_MANIFEST.json`. Simple baselines included with honest scores (Hindi 0.31, Telugu 0.38, Hinglish 0.26 macro-F1, humor 0.56). Low numbers on purpose: floors for future models to beat.

Memory. A small store with add, retrieve, conflict handling, and a forget that really deletes. Tested with 27 facts plus adversarial controls: 27/27 recalled, zero leaks from forgotten facts. Later I gave it human habits (working memory, salience, decay, rehearsal) and the forget guarantee still holds. The app auto-saves facts from conversation in the background.

Models. Qwen3-1.7B fine-tuned with DoRA on a rented H100 through Modal, on 20,017 real Hindi+Telugu conversation continuations. Result: eval loss 1.52 (base) down to 1.09, both languages. Served warm at 62 ms against a 200 ms budget. Speech is a fine-tuned whisper-small (Hindi error rate 89.5% down to 31.9%, Telugu 109% down to 55.5%) plus Indic Parler TTS. Total cloud spend stayed around $17.

The app. A Go gateway (stdlib only) over the Modal GPU workers, a Next.js UI, push-to-talk voice and chat side by side. Five modes: our voice, our chat, Sarvam voice, Sarvam chat, and the hybrid I actually use (our speech recognition, Sarvam's large model for replies, our speech synthesis). Memory panel included.

## How I built it

Some of this I did by hand, some with an AI coding agent, and the split matters.

I made every judgment call myself: which datasets live or die, shrinking the scope to the data suite instead of a 200-person collection I could not staff, and every dashboard step that needs a human (Kaggle login, Hugging Face token, Render, Vercel, the Sarvam key). I also wrote the Go backend line by line. Typing it myself is slow and that is the point; it is the part of the codebase I can explain cold.

I caught bugs by using the thing. Talking to it in a real browser surfaced everything the tests missed: rooms answering garbage, listening cut mid-sentence, the app hearing its own replies as new turns, gibberish when I spoke English. Each complaint turned into a measured fix in `NOTES.md`.

The agent earned its keep on measurement. Every serving bug was caught by a check, not by staring: the model sitting on CPU for 12.4 seconds, missing GPU warm-up, a precision bug that corrupted every merged weight, training labels poisoned by invisible chat-template markers, a Telugu batch blowing past 80 GB of VRAM, token caps silently cutting a third of Telugu evals. The log in `NOTES.md` (parts 1 to 55) tells each story with the failing number kept next to the passing one. That is how you know the passing ones are real.

The part I like most is the forget. Anyone can store facts; proving nothing leaks after deletion, including under an injection attack, is rarer and it holds.

## Limits, stated plainly

English audio into our speech model comes back as Devanagari babble. It is a Hindi/Telugu recognizer and I treat it as one. Telugu trails Hindi everywhere. Full spoken replies take seconds (speech synthesis dominates), so expect walkie-talkie pacing. On the free hosting tier the server sleeps when idle (first request wakes it) and memory resets on restart. Emotional intelligence is still future work: the model continues conversations well but has no empathy supervision yet.

## Run it

Local, three processes:

```bash
python3 research/memory/sidecar.py   # memory on :18081
cd backend && go run ./cmd/api        # gateway on :8080
cd frontend/awaaz-ui && npm run dev   # UI on :3000
```

Set `SARVAM_API_KEY` for the Sarvam modes. `GATEWAY_URL` points the UI at a gateway; `NEXT_PUBLIC_API_URL` skips the proxy. The rest of the knobs (`ADDR`, `CORS_ORIGINS`, `MEMORY_URL`, rate limits) have sane defaults in the README's old config table, now trimmed: see `backend/internal/config/config.go`.

Checks:

```bash
cd backend && go test ./...
python3 research/memory/run_eval.py && python3 research/memory/run_human_eval.py
cd frontend/awaaz-ui && npm run typecheck && npm run lint
```

Training and serving scripts live in `research/training/` with their commands in `results/RESULTS.md`. Note the voice protocol changed: the old WebSocket rooms are deleted after they caused more problems than they solved. Voice is one POST per turn now (`/api/v1/voice`), hold to talk.

## Files

`research/spec.md` is the original research plan. `research/DATASET_CARD.md`, `research/ANNOTATION_PROTOCOL.md`, and `research/benchmark/` are the data and collection specs. `NOTES.md` is the full build log. `results/` holds every measured number as JSON. `ARTICLE.md` and `JOURNEY.md` are my own writeups in my own words.

## References

Datasets I used:

- EmoInHindi (Singh et al., LREC 2022): https://aclanthology.org/2022.lrec-1.627/
- BHAAV Hindi stories: https://arxiv.org/abs/1910.04073
- Telugu emotion text: https://arxiv.org/abs/2205.01204
- MaSaC / SemEval-2024 Task 10 EDiReF: https://aclanthology.org/2024.semeval-1.270/
- M2H2 Hindi humor (ICMI 2021): https://arxiv.org/abs/2108.01260
- CMU Hinglish DoG chats: https://huggingface.co/datasets/festvox/cmu_hinglish_dog
- Sowmith Telugu speech: https://www.kaggle.com/datasets/jettysowmith/telugu-emotion-speech
- IndicVoices (AI4Bharat, CC BY 4.0): https://huggingface.co/datasets/ai4bharat/IndicVoices
- KuralHub Indic speech-emotion survey (my completeness check): https://github.com/aaivu/KuralHub
- LoCoMo long-conversation memory benchmark: https://github.com/snap-research/locomo
- HumDial-EIBench (external diagnostic only, never trained on): https://huggingface.co/datasets/ASLP-lab/HumDial-EIBench

Models and methods I used:

- Qwen3-1.7B-Base: https://huggingface.co/Qwen/Qwen3-1.7B-Base
- Whisper (Radford et al., 2022): https://arxiv.org/abs/2212.04356
- DoRA (Liu et al., 2024): https://arxiv.org/abs/2402.10953
- LoRA (Hu et al., 2021): https://arxiv.org/abs/2106.09685
- Indic Parler TTS (AI4Bharat, Apache 2.0): https://huggingface.co/ai4bharat/indic-parler-tts
- Sarvam AI API, Saaras transcriber, Bulbul voice, sarvam-105b-conversations: https://docs.sarvam.ai

Built with Modal (H100 rentals), Go, Next.js, and SQLite. Nothing else bills.
