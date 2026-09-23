# Memory sidecar

The memory sidecar is a local Python HTTP service in `research/memory/sidecar.py`. It keeps one user's facts in SQLite, with retrieval indexes rebuilt from the stored facts at startup. The default bind address is `127.0.0.1:18081`; the Go gateway reaches it through `MEMORY_URL`.

The sidecar's routes are internal. For app use, call the gateway's `/api/v1/memory` routes described in the [gateway API reference](gateway-api.md).

## Sidecar routes

| Method | Path | Request | Result |
|---|---|---|---|
| `GET` | `/healthz` | — | `status`, active fact count, and whether LLM enrichment is enabled |
| `GET` | `/facts` | — | `{"facts":[...]}` |
| `POST` | `/add` | `{"text":"..."}` | Fact `id` and `text` |
| `POST` | `/forget` | `{"text":"..."}` | `{"forgot":true|false}` |
| `POST` | `/context` | `{"query":"..."}` | Retrieved context block |
| `POST` | `/observe` | `{"utterance":"..."}` | Facts captured from the utterance |

The HTTP body limit is 1 MiB and a captured utterance is limited to 4,000 characters.

## How the app uses memory

- The chat handler asks the sidecar for context using the latest user message before calling the chat model.
- After a successful chat reply, the gateway submits that user turn for automatic observation without delaying the reply.
- Observation applies synchronous rules first. Optional LLM enrichment runs in a background worker with a bounded queue.
- The memory panel lists facts and lets a user add or explicitly forget one.
- The current direct HTTP voice handler does not submit voice turns for automatic observation.

LLM enrichment is optional. The sidecar stays rules-only unless `MEMORY_LLM_URL` and `MEMORY_LLM_KEY` are configured. Keep the key in the runtime environment; do not commit it.

## Persistence and forgetting

Set `MEMORY_DB` to choose the SQLite file. In the container, `start.sh` runs the gateway and sidecar together and the Render blueprint points `MEMORY_DB` at `/data/memory.db`. The current free Render blueprint does not attach a persistent disk, so that file may not survive a service restart.

Explicit forgetting purges the fact text from the live store and retrieval indexes, clears matching working-memory text, cascades to derived facts, and persists the forgotten status. The status record remains so the store can track that the fact was forgotten; its text is cleared.

## Deployment boundary

This implementation is a single-user demo store. The gateway and sidecar do not add user authentication or tenant-level isolation to memory routes. Keep the sidecar on its local bind address and do not expose these routes to untrusted callers without adding access control and per-user storage boundaries.
