# Gateway API

The Go gateway listens on port `8080` by default. Set `ADDR` or `PORT` to change the listen address. The same routes are available through the Next.js proxy when the UI is running; see [local development](development.md).

All request and response bodies use JSON unless noted. Errors use this shape:

```json
{
  "error": {
    "code": "error_code",
    "message": "Short description"
  }
}
```

## Routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Gateway health check |
| `POST` | `/api/v1/chat` | Text chat |
| `POST` | `/api/v1/voice` | One speech or text-to-speech turn |
| `POST` | `/api/v1/warm` | Start background ASR and TTS warm-up probes; returns `204 No Content` |
| `GET` | `/api/v1/memory` | List visible memory facts |
| `POST` | `/api/v1/memory` | Add a memory fact |
| `POST` | `/api/v1/memory/forget` | Explicitly forget a memory fact |

## Health

```bash
curl http://localhost:8080/healthz
```

A healthy gateway returns `200` with `{"status":"ok"}`.

## Text chat

Send a non-empty `messages` array. Each item needs a `role` and `content`. `max_tokens` defaults to `50` and must be between `1` and `200`. Omit `provider` to use the Awaaz model; set it to `sarvam` to use Sarvam when its API key is configured.

```bash
curl http://localhost:8080/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "messages": [
      {"role": "user", "content": "Tell me about your day"}
    ],
    "max_tokens": 80
  }'
```

A successful response contains `reply` and `model`; `server_ms` is included when the upstream returns a positive duration. If memory is available, the gateway may prepend retrieved context for the latest user message.

## Voice

The request must contain either `wav_b64` or `text`. `lang` accepts `hi`, `te`, or `auto` and defaults to `auto`. When audio is supplied, `wav_b64` must be valid base64 whose decoded content is under 2 MiB. The bundled UI records a clip, converts it to 16 kHz mono WAV, and sends one request when the user releases the talk button.

The default provider path uses Awaaz ASR and TTS. Set `llm` to `sarvam` to use Sarvam for the reply model while keeping Awaaz ASR/TTS. Set `provider` to `sarvam` for the full Sarvam voice path.

```json
{
  "lang": "auto",
  "wav_b64": "<base64-encoded WAV>",
  "provider": "awaaz",
  "llm": "sarvam"
}
```

For the Awaaz pipeline, the response includes `heard`, `reply`, `asr`, `llm`, and `audio_b64`; stage timings are included when available. The full Sarvam voice path returns `heard`, `reply`, `asr`, and `audio_b64`.

## Memory

The gateway exposes the sidecar through these routes:

- `GET /api/v1/memory` returns `{"facts":[{"id":1,"text":"..."}]}`.
- `POST /api/v1/memory` accepts `{"text":"..."}` and returns the new fact's `id` and `text`.
- `POST /api/v1/memory/forget` accepts `{"text":"..."}` and returns `{"forgot":true}` or `{"forgot":false}`.

See [memory sidecar](memory.md) for automatic capture, persistence, and forgetting behavior.
