package handler

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"awaaz/internal/memory"
)

// fakeSidecar stands in for research/memory/sidecar.py.
type fakeSidecar struct {
	observed []string
	facts    []memory.Fact
	block    string
	used     []memory.Recalled
}

func (f *fakeSidecar) server(t *testing.T) *memory.Client {
	t.Helper()
	mux := http.NewServeMux()
	mux.HandleFunc("POST /context", func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{
			"block": f.block, "used": f.used,
		})
	})
	mux.HandleFunc("POST /observe", func(w http.ResponseWriter, r *http.Request) {
		var in struct {
			Text string `json:"text"`
		}
		_ = json.NewDecoder(r.Body).Decode(&in)
		f.observed = append(f.observed, in.Text)
		_ = json.NewEncoder(w).Encode(map[string]any{"captured": f.facts})
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return memory.NewClient(srv.URL)
}

// TestChatRecallsAndCaptures proves the typed surface both reads and writes
// memory, and reports each in the response.
func TestChatRecallsAndCaptures(t *testing.T) {
	sc := &fakeSidecar{
		block: "MEMORY:\n- I work at a hospital",
		used:  []memory.Recalled{{ID: 2, Text: "I work at a hospital", Importance: 0.9}},
		facts: []memory.Fact{{ID: 3, Text: "my name is Raj"}},
	}
	h := New(&fakeGateway{})
	h.UseMemory(sc.server(t))

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat",
		strings.NewReader(`{"messages":[{"role":"user","content":"my name is Raj"}]}`))
	NewMux(h).ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rec.Code, rec.Body)
	}
	var out struct {
		MemoryUsed  []memory.Recalled `json:"memory_used"`
		MemorySaved []memory.Fact     `json:"memory_saved"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(out.MemoryUsed) != 1 || out.MemoryUsed[0].Text != "I work at a hospital" {
		t.Errorf("recall not reported to the client: %+v", out.MemoryUsed)
	}
	if len(out.MemorySaved) != 1 || out.MemorySaved[0].Text != "my name is Raj" {
		t.Errorf("capture not reported to the client: %+v", out.MemorySaved)
	}
	if len(sc.observed) != 1 || sc.observed[0] != "my name is Raj" {
		t.Errorf("the user's turn was not offered for capture: %v", sc.observed)
	}
}

// TestChatCapturesEvenWhenModelFails is the durability guarantee: a stated
// fact must survive an upstream outage. Capture therefore runs before the
// model call, not after it.
func TestChatCapturesEvenWhenModelFails(t *testing.T) {
	sc := &fakeSidecar{facts: []memory.Fact{{ID: 1, Text: "my name is Raj"}}}
	h := New(&fakeGateway{chatErr: errors.New("upstream down")})
	h.UseMemory(sc.server(t))

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat",
		strings.NewReader(`{"messages":[{"role":"user","content":"my name is Raj"}]}`))
	NewMux(h).ServeHTTP(rec, req)

	if rec.Code == http.StatusOK {
		t.Fatal("expected the upstream failure to surface")
	}
	if len(sc.observed) != 1 {
		t.Fatalf("fact was lost when the model failed: %v", sc.observed)
	}
}

// TestMemoryDegradesWhenSidecarDown proves memory is best-effort: no sidecar
// must never mean no answer.
func TestMemoryDegradesWhenSidecarDown(t *testing.T) {
	h := New(&fakeGateway{})
	// Point at a closed port.
	h.UseMemory(memory.NewClient("http://127.0.0.1:1"))

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat",
		strings.NewReader(`{"messages":[{"role":"user","content":"hello"}]}`))
	NewMux(h).ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("a down sidecar broke chat: %d %s", rec.Code, rec.Body)
	}
}

// TestWithMemoryPrependsBlock covers the voice prompt assembly, which has no
// system role to put the context in.
func TestWithMemoryPrependsBlock(t *testing.T) {
	if got := withMemory("where do I work", ""); got != "where do I work" {
		t.Errorf("empty block must pass the turn through, got %q", got)
	}
	got := withMemory("where do I work", "MEMORY:\n- at a hospital")
	if !strings.Contains(got, "MEMORY:") || !strings.HasSuffix(got, "where do I work") {
		t.Errorf("block not prepended: %q", got)
	}
}
