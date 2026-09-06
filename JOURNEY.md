# My Journey: Finding AI Bugs and Getting Better

I started this project to get a job in AI. What I actually got was an education
in how machine learning breaks — because almost everything I built failed first,
and each failure taught me something no tutorial covers.

## Where I started

I had a MacBook, no GPU budget to speak of ($10 ceiling), two Indian languages
with almost no good data, and a job posting asking for memory systems,
fine-tuning, and sub-200 ms serving. So I built all three, in Hindi and Telugu,
for about $16 total.

## The data discipline (the boring part that matters most)

Before any model, I assembled 83,196 native-authored records and later 610,000
real Hindi and Telugu utterances from consented, licensed sources. My rule never
moved: no machine-translated data, no synthetic labels, no unverified consent.
I rejected easy datasets four separate times for violating it. Lesson one:
**in low-resource AI, data honesty is the whole game.**

## The bugs that taught me — each one real, each one measured

**1. The model that ran on CPU ($0 lesson, 12,430 ms).**
My serving code attached an H100 but never moved the model to it. Every request
took 12 seconds. Lesson: *attaching hardware is not using hardware — verify
device placement, always.*

**2. The 391 ms first call.**
Lazy CUDA kernel loading made the first request slow even on GPU. Lesson:
*warm up at container startup, never on the user's first request.*

**3. The merge that corrupted everything.**
Merging my DoRA adapter into bf16 weights produced one garbage token for every
prompt. The model looked completely broken; the weights were fine — the merge
math wasn't. Lesson: *verify outputs after every transformation, especially
precision-sensitive ones.*

**4. The template that poisoned my labels.**
The chat template wrapped every training answer in invisible think-markers, so
my model learned to emit garbage prefixes. I found it by printing exactly what
the encoder fed the model. Lesson: *never trust a formatting layer — inspect
your actual training bytes.*

**5. The missing stop token.**
My labels ended turns with `<|im_end|>`, but the base model only stopped on
`<|endoftext|>`. The model rambled into hallucinated next-user-turns and nobody
could see why, because the markers were hidden. Lesson: *the train/serve
contract includes tokenization details, not just weights.*

**6. The out-of-memory at step 1114.**
Telugu utterances run longer than Hindi; one long batch blew past 80 GB.
Lesson: *cap sequence lengths, enable expandable segments, and know your
data's tail — not just its average.*

**7. The whisper labels with no language.**
I trained Hindi and Telugu speech with identical label prefixes, then evaluated
with language tokens the model never saw. Telugu barely improved. Lesson:
*train and eval must speak the same format — a mismatch hides inside good
aggregate numbers.*

**8. The 691-token Telugu sentence.**
Whisper's tokenizer needs several tokens per Telugu character. My 200-token cap
silently cut 16% of Telugu training data and 31% of evals. Lesson: *measure
your data's token distribution before setting any cap.*

**9. Greedy decoding loops.**
Casual chat made the model echo one word forever. Sampling fixed it; then
repetition penalties and n-gram blocks made things *worse* by pushing a small
model into foreign-script junk. Lesson: *decoding config is a real engineering
surface, and constraints can push small models off-manifold.*

**10. The $2.6 silent preprocessing.**
I extracted features for 16,000 clips to keep 4,000 — on billed H100 silicon,
with no progress output, for 40 minutes. Lesson: *never preprocess bulk data
on expensive hardware; slice first, print heartbeats.*

**11. The small ones that still matter.**
A validator that couldn't see f-strings, a volume download that needed its
folder pre-created, a Go shutdown that didn't wait for draining requests, a
panic handler that returned HTTP 200, an unbounded `max_tokens` on a paid GPU.
Lesson: *oracles and gates catch what eyes miss — automate every check.*

## What the numbers say now

- Bilingual fine-tune: −28% loss vs base, both languages
- Speech recognition: Hindi error rate 89.5% → 41.4% (beats a 3× bigger model)
- Serving: 62 ms warm against a 200 ms budget
- Memory system: 27/27 recall, zero leaks, plus human-like dynamics (working
  memory, rehearsal, salience, decay) — all passing
- Full voice loop (speech → model → speech) running in both languages

## How I'm improving myself

1. **I'm writing the backend myself** (Go, stdlib only) — guided, not generated.
   Typing every line is slow and that's the point.
2. **I'm learning to explain, not just build.** Each bug above is a two-minute
   interview story: what I saw, what I measured, what I changed.
3. **Next technical steps:** multi-turn conversation windows for training data,
   streaming speech for real-time voice, and bigger base models when budget allows.
4. **The real mountain:** emotional intelligence needs labeled emotional data
   from real native speakers. No model trick substitutes for it. That's the
   future work — and knowing exactly what it costs is itself an answer.

The pattern across all of it: measure first, assume nothing, write down what
failed. That habit is the actual skill. The models are just where I practiced it.
