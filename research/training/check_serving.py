"""G5 oracle: warm server-side first-token latency under the 200 ms budget.

Client wall time is recorded but never asserted (network RTT pollutes it;
the budget is about serving infra). Prints SERVE_OK only when all three warm
calls return server_ms < 200 with a non-empty token.
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

URL_FILE = Path("research/training/endpoint.url")
RESULTS = Path("results/serving_latency.json")
BUDGET_MS = 200
PROMPT = {"messages": [{"role": "user", "content": "नमस्ते, आज मेरा दिन अच्छा नहीं गया।"}]}


def post(url):
    request = urllib.request.Request(
        url, data=json.dumps(PROMPT).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body, (time.perf_counter() - started) * 1000


def main():
    if not URL_FILE.is_file():
        print(f"SERVE_FAIL: missing {URL_FILE} (run modal deploy first)", file=sys.stderr)
        return 1
    url = URL_FILE.read_text(encoding="utf-8").strip()

    print("warming container (first call may take minutes)...", file=sys.stderr)
    post(url)

    measurements = []
    for _ in range(3):
        body, client_ms = post(url)
        measurements.append({
            "server_ms": body.get("server_ms"),
            "client_ms_measured": round(client_ms, 2),
            "token": body.get("token"),
        })

    report = {"endpoint": url, "budget_ms": BUDGET_MS, "measurements": measurements}
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    failures = [
        f"call {i + 1}: server_ms={m['server_ms']} token={m['token']!r}"
        for i, m in enumerate(measurements)
        if m["server_ms"] is None or m["server_ms"] >= BUDGET_MS or not m["token"]
    ]
    if failures:
        for failure in failures:
            print(f"SERVE_FAIL over budget: {failure}", file=sys.stderr)
        return 1
    print("SERVE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
