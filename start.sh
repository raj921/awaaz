#!/bin/sh
# Runs the Go gateway and the memory sidecar in one container.
# All secrets arrive as env (never baked in): SARVAM_API_KEY,
# MEMORY_LLM_URL, MEMORY_LLM_KEY. MEMORY_DB should point at a volume.
python3 /app/memory/sidecar.py &
exec /app/api
