# Emotional AI for Hindi and Telugu — and a production LLM pipeline for $1.62

Job posts for AI engineers ask for three things: a long-term memory system, hands-on fine-tuning, and serving under a tight latency budget. I built all three for Indian languages. The whole cloud bill came to $1.62.

## The problem with emotional AI in Indian languages

Most "Hindi" emotion datasets you find online are machine-translated. Translated text does not carry how people actually feel. A speaker saying "mann nahi hai" means something that an English gloss loses completely. So I set a strict rule for my project: only data written or spoken by native speakers. No machine translation, no synthetic data, no labels or consent I cannot verify.

## The data suite

I assembled 83,196 processed records from eight pinned sources:

- **bhaav** — emotion-labeled Hindi stories
- **Telugu Emotion (IIIT-H)** — Telugu text with emotion labels
- **MaSaC (SemEval-2024)** — code-mixed Hindi-English conversation emotion
- **M2H2** — humor dialogues in native Devanagari
- **CMU Hinglish DoG** — document-grounded Hinglish conversations
- **Sowmith Telugu SER** — Telugu emotional speech

Every source is checksummed in a manifest. The consent fields are hard-coded as true in the validation schema, so a record with fabricated consent simply cannot pass.

## Honest baselines

I trained simple classifiers and published the real numbers:

- Emotion classification, test macro-F1: **Hindi 0.31, Telugu 0.38, Hinglish 0.26**
- Humor detection on M2H2 dialogues: **0.56**

These numbers are low. That is the point. Low-resource languages with small labeled data give low numbers, and pretending otherwise would make the benchmark useless. I publish per-class scores and limitations, not just a headline.

## A memory system that actually forgets

Assistants need long-term memory. The hard part is not storing. It is deleting. My store supports add, retrieve, conflict handling (a newer fact supersedes an older conflicting one), and a real forget operation. The evaluation does not just check that the assistant remembers 27 facts across a conversation. It checks that nothing from forgotten facts leaks into responses, including an adversarial injection test. Result: 27/27 recalled, zero leaks.

## Fine-tuning on a rented H100

I fine-tuned Qwen3-1.7B with DoRA (a newer LoRA variant with better accuracy at the same inference cost), rank 16, on a rented H100 through Modal. Two things I did that are worth knowing:

1. I hand-rolled the loss masking. The training loss is computed only on the assistant's tokens. The standard TRL flag for this needs chat-template markers that Qwen3 does not have, so I masked the prompt manually.
2. The base model is downloaded once to a cloud volume by a cheap CPU function. The expensive GPU never spends billed time waiting on downloads.

The smoke run: 30 steps, final loss 4.73, adapter saved and downloaded as a real artifact.

## 20 milliseconds

The fine-tuned adapter is merged into the model and served behind an HTTPS endpoint. Latency is measured inside the container, because a client-side number from India to a US server mostly measures geography. The budget was 200 ms. Warm first-token time: about **20 ms**.

The interesting part is what my gate checks caught before anything looked good:

1. The first version ran at **12,430 ms** — because the model was never moved to the GPU. `from_pretrained` loads to CPU, and attaching an H100 does not move it. One line, `.to("cuda")`, took it to 391 ms.
2. The first measured call was still 391 ms — lazy CUDA kernel loading. Warm-up now happens at container start, not on the user's first request.

I kept the failing numbers in the writeup. That is how you know the passing ones are real.

## Cost and discipline

Total cloud spend: **$1.62** against a $10 ceiling. Containers are stopped after every pass. Every claim above reproduces from commands in the README, and a seven-gate ledger verifies each outcome with tool-run evidence.

## What is next

Full training on real native conversations, not just the smoke run. There are now licensed sources of consented conversational speech in Hindi and Telugu (IndicVoices alone has roughly 1,700 hours of conversations from 51,000 consenting speakers). After that, voice: speech recognition and synthesis under the same per-stage latency budgets.

The gap for Indian-language emotional AI is not the models. It is native data treated with respect, and honest numbers published even when they are low.
