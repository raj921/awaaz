
## 2026-09-05 — Part 33: Voice 400 diagnosed — long clip + generic error

- User's voice turn 400d: body past the 4 MiB middleware cap (long recording), misreported as "invalid request body". Fixed both ends: frontend auto-stops recording at 30 s; backend names MaxBytesError honestly ("request body too large, keep clips under 30 seconds", verified live with a 5 MB probe). gofmt/vet/build/tests + frontend build green.

## 2026-09-06 — Part 54: "Unable to decode audio data" — empty-clip guard

- User got decode errors on push-to-talk release. Two suspect paths checked: backend reply audio verified valid RIFF, so it's the recording side — a fast release can yield a 0-byte MediaRecorder clip (final dataavailable arrives on the next tick), which the page then fed straight into decodeAudioData. Fix: onstop now checks blob size and shows an honest message instead of a decode failure ("no speech captured — hold a little longer").
- Full dev cycle redone (fresh bun run dev) since edits to hooks don't always hot-swap; page verified serving.
