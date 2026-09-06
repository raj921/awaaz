# Gates: Go backend gateway

OWNS: backend/**, GATES-B.md

Scope: stateless Go gateway over the Modal GPU workers (chat + voice), stdlib
only, honest errors, table-driven tests. Same philosophy as every other phase:
no fake anything (tests use explicit fakes, never the live GPU), every claim
tool-verified, missing pieces named (auth, persistence, memory) — never hidden.

- [x] G1: this ledger states outcomes that can fail
  CHECK: node /Users/rajkumar/.agents/skills/unlazy/scripts/gate-lint.mjs GATES-B.md
  EXPECT: LINT OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/rajkumar/rumikhire; path=e89d98c46c5e/63 entries; EXPECT=matched; output-sha256=703754cc0ab7ab19f15ffa4ef8acf8ed52c44ccc5759fb1264c9e3cf8381fa3b; output-bytes=152

- [x] G2: everything formatted, vetted, and compiling
  CHECK: sh -c 'cd backend && gofmt -l . | grep . && exit 1; go vet ./... && go build ./... && echo GO_BUILD_OK'
  EXPECT: GO_BUILD_OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/rajkumar/rumikhire; path=e89d98c46c5e/63 entries; EXPECT=matched; output-sha256=250b9b2b0f161708a5cce8d225769628bbf63e1165683eaf77779d85c78eaea5; output-bytes=12

- [x] G3: table-driven tests pass with no network and no GPU
  CHECK: sh -c 'cd backend && go test ./... && echo GO_TESTS_OK'
  EXPECT: GO_TESTS_OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/rajkumar/rumikhire; path=e89d98c46c5e/63 entries; EXPECT=matched; output-sha256=d4a819a55288fa8e7d5c90e375d03534ff3c31e982dd20510a483e95535dcb60; output-bytes=242

- [x] G4: server boots and answers /healthz live
  CHECK: sh -c 'cd backend && go build -o /tmp/be-server ./cmd/api && (ADDR=:18080 /tmp/be-server & echo $! > /tmp/be.pid); sleep 2; code=$(curl -s -o /dev/null -w "%{http_code}" localhost:18080/healthz); kill $(cat /tmp/be.pid) 2>/dev/null; [ "$code" = 200 ] && echo BACKEND_LIVE'
  EXPECT: BACKEND_LIVE
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/rajkumar/rumikhire; path=e89d98c46c5e/63 entries; EXPECT=matched; output-sha256=41fd9a96141df87a30df6bef34e87527737f05d34ffd70c502c86a5f98f1e182; output-bytes=211

- [x] G5: a real model reply flows end-to-end through the backend (needed Modal deployed)
  EVIDENCE: modal deploy qwen3-a1-serve OK → check_serving.py SERVE_OK → POST localhost:18080/api/v1/chat {"messages":[{"role":"user","content":"हलो"}]} → HTTP 200 {"model":"qwen3-1.7B+a2-bilingual","reply":"आप भेज देंगे आपकी प्रोफ़ाइल अपने बायोग्राफी कैमरा में","server_ms":1966.29}; app stopped after

- [x] G6: overload behavior verified — excess sheds load instead of crashing (tested, no scale claims)
  CHECK: sh -c 'cd backend && go test ./internal/handler/ -run "TestOverload|TestRateLimit" -v && echo GO_OVERLOAD_OK'
  EXPECT: GO_OVERLOAD_OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/rajkumar/rumikhire; path=e89d98c46c5e/63 entries; EXPECT=matched; output-sha256=837e736658138146dc2bcce928e95a795fc60066f9e2420bf6d72731d3968bd5; output-bytes=113
