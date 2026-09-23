# Local development

Awaaz runs locally as three processes: the Python memory sidecar, the Go gateway, and the Next.js UI.

## Requirements

- Go matching the version in `backend/go.mod` (Go 1.24.2).
- Python 3 with the standard `sqlite3` module.
- Bun for the UI dependencies and scripts; the frontend includes `bun.lock`.

## Start the services

Use three terminals from the repository root.

**Terminal 1 — memory sidecar**

```bash
python3 research/memory/sidecar.py
```

The default address is `127.0.0.1:18081`. To use a different SQLite file, set `MEMORY_DB` before starting it.

**Terminal 2 — Go gateway**

```bash
cd backend
go run ./cmd/api
```

The default listen address is `:8080`. The gateway's `MEMORY_URL` default points to the sidecar above.

**Terminal 3 — browser UI**

```bash
cd frontend/awaaz-ui
bun install
GATEWAY_URL=http://127.0.0.1:8080 bun run dev
```

Next.js serves the UI at `http://localhost:3000`. In local development, `GATEWAY_URL` is important: the Next rewrite defaults to port `18080`, while the Go gateway defaults to `8080`.

Open the UI at `http://localhost:3000`. Check the gateway directly with:

```bash
curl http://127.0.0.1:8080/healthz
```

## Useful environment variables

| Variable | Used by | Default or purpose |
|---|---|---|
| `ADDR` / `PORT` | Go gateway | Listen address; `ADDR` wins, otherwise `PORT` defaults to `8080` |
| `MEMORY_URL` | Go gateway | Sidecar URL, default `http://127.0.0.1:18081` |
| `CORS_ORIGINS` | Go gateway | Allowed browser origins, default `http://localhost:3000` |
| `SARVAM_API_KEY` | Go gateway | Enables Sarvam provider options |
| `MEMORY_DB` | Python sidecar | SQLite file path; defaults beside `sidecar.py` |
| `MEMORY_LLM_URL` and `MEMORY_LLM_KEY` | Python sidecar | Enable optional background LLM enrichment |
| `GATEWAY_URL` | Next.js server | Target for same-origin API rewrites; set to `http://127.0.0.1:8080` locally |
| `NEXT_PUBLIC_API_URL` | Browser UI | Optional direct gateway URL; when unset, requests use the same-origin Next.js rewrite |

Keep API keys in environment variables or your deployment secret store. Do not commit them.

## Checks

Run the checks from the relevant project directories:

```bash
cd backend && go test ./...
python3 research/memory/run_eval.py
python3 research/memory/run_human_eval.py
cd frontend/awaaz-ui && bun run typecheck
cd frontend/awaaz-ui && bun run lint
```

To use memory during chat, start the sidecar as well as the gateway. To use Sarvam modes, configure `SARVAM_API_KEY`. LLM enrichment is optional and disabled unless both `MEMORY_LLM_URL` and `MEMORY_LLM_KEY` are set.
