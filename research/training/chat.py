"""Try the bilingual hi/te model. Type Hindi or Telugu, get replies. Ctrl-C to quit.

First: .venv/bin/modal deploy research/training/serve_qwen3.py
After:  .venv/bin/modal app stop qwen3-a1-serve --yes   (stop the meter)
"""

import json
import urllib.request

URL = "https://raj315920--qwen3-a1-serve-first-token.modal.run"


def ask(text, max_tokens=60):
    body = json.dumps({"messages": [{"role": "user", "content": text}],
                       "max_tokens": max_tokens}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    out = json.loads(urllib.request.urlopen(req, timeout=300).read())
    return out["token"], out["server_ms"]


def main():
    print("Bilingual Hindi/Telugu model. First message may take ~1 min (container warm-up).")
    while True:
        try:
            text = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye. Stop the meter: .venv/bin/modal app stop qwen3-a1-serve --yes")
            break
        if not text:
            continue
        reply, ms = ask(text)
        print(f"Model ({ms:.0f} ms): {reply}")


if __name__ == "__main__":
    main()
