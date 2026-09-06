package handler

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"awaaz/internal/modal"
)

type fakeGateway struct {
	chatReply modal.ChatResult
	chatErr   error
	voiceOut  modal.VoiceResult
	voiceErr  error
	asrOut    string
	asrErr    error
}

func (f *fakeGateway) Chat(
	_ context.Context, _ []modal.ChatMessage, _ int,
) (modal.ChatResult, error) {
	return f.chatReply, f.chatErr
}

func (f *fakeGateway) ChatVoice(
	_ context.Context, _ string, _ int,
) (modal.ChatResult, error) {
	return f.chatReply, f.chatErr
}

func (f *fakeGateway) Voice(
	_ context.Context, _, _, _ string,
) (modal.VoiceResult, error) {
	return f.voiceOut, f.voiceErr
}

func (f *fakeGateway) Asr(
	_ context.Context, _, _, text string,
) (string, float64, error) {
	if f.asrOut != "" {
		return f.asrOut, 1, nil
	}
	return text, 1, f.asrErr
}

func (f *fakeGateway) Tts(
	_ context.Context, text string,
) (string, float64, error) {
	return "audio:" + text, 1, nil
}

func TestHealth(t *testing.T) {
	mux := NewMux(New(&fakeGateway{}))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/healthz", nil))

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	var body map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("body is not JSON: %v", err)
	}
	if body["status"] != "ok" {
		t.Fatalf("status = %q, want ok", body["status"])
	}
}

func TestChat(t *testing.T) {
	tests := []struct {
		name       string
		body       string
		fake       *fakeGateway
		wantStatus int
		wantCode   string
		wantReply  string
	}{
		{
			name:       "success",
			body:       `{"messages":[{"role":"user","content":"हलो"}],"max_tokens":10}`,
			fake:       &fakeGateway{chatReply: modal.ChatResult{Reply: "हाँ बोलिए", ServerMs: 42}},
			wantStatus: http.StatusOK,
			wantReply:  "हाँ बोलिए",
		},
		{
			name:       "invalid json",
			body:       `{broken`,
			fake:       &fakeGateway{},
			wantStatus: http.StatusBadRequest,
			wantCode:   "BAD_REQUEST",
		},
		{
			name:       "empty messages",
			body:       `{"messages":[]}`,
			fake:       &fakeGateway{},
			wantStatus: http.StatusUnprocessableEntity,
			wantCode:   "VALIDATION_ERROR",
		},
		{
			name:       "missing content",
			body:       `{"messages":[{"role":"user","content":""}]}`,
			fake:       &fakeGateway{},
			wantStatus: http.StatusUnprocessableEntity,
			wantCode:   "VALIDATION_ERROR",
		},
		{
			name:       "max tokens out of range",
			body:       `{"messages":[{"role":"user","content":"hi"}],"max_tokens":500}`,
			fake:       &fakeGateway{},
			wantStatus: http.StatusUnprocessableEntity,
			wantCode:   "VALIDATION_ERROR",
		},
		{
			name:       "upstream down maps to 502",
			body:       `{"messages":[{"role":"user","content":"hi"}]}`,
			fake:       &fakeGateway{chatErr: errors.New("connection refused")},
			wantStatus: http.StatusBadGateway,
			wantCode:   "UPSTREAM_ERROR",
		},
		{
			name:       "upstream timeout maps to 504",
			body:       `{"messages":[{"role":"user","content":"hi"}]}`,
			fake:       &fakeGateway{chatErr: context.DeadlineExceeded},
			wantStatus: http.StatusGatewayTimeout,
			wantCode:   "UPSTREAM_TIMEOUT",
		},
		{
			name:       "busy GPUs map to 503",
			body:       `{"messages":[{"role":"user","content":"hi"}]}`,
			fake:       &fakeGateway{chatErr: &modal.UpstreamError{Status: 429}},
			wantStatus: http.StatusServiceUnavailable,
			wantCode:   "SERVICE_UNAVAILABLE",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			mux := NewMux(New(tt.fake))
			rec := httptest.NewRecorder()
			mux.ServeHTTP(rec, httptest.NewRequest(
				http.MethodPost, "/api/v1/chat", strings.NewReader(tt.body)))

			if rec.Code != tt.wantStatus {
				t.Fatalf("status = %d, want %d (body: %s)", rec.Code, tt.wantStatus, rec.Body.String())
			}
			var body map[string]any
			if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
				t.Fatalf("body is not JSON: %v", err)
			}
			if tt.wantReply != "" && body["reply"] != tt.wantReply {
				t.Fatalf("reply = %v, want %q", body["reply"], tt.wantReply)
			}
			if tt.wantCode != "" {
				errObj, _ := body["error"].(map[string]any)
				if errObj["code"] != tt.wantCode {
					t.Fatalf("code = %v, want %q", errObj["code"], tt.wantCode)
				}
			}
		})
	}
}

func TestOverload(t *testing.T) {
	mux := Overload(NewMux(New(&fakeGateway{})), 0, 1000, 1000)

	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest(
		http.MethodPost, "/api/v1/chat", strings.NewReader(`{"messages":[{"role":"user","content":"hi"}]}`)))
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("overloaded chat status = %d, want 503", rec.Code)
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("body is not JSON: %v", err)
	}
	errObj, _ := body["error"].(map[string]any)
	if errObj["code"] != "SERVICE_UNAVAILABLE" {
		t.Fatalf("code = %v, want SERVICE_UNAVAILABLE", errObj["code"])
	}

	health := httptest.NewRecorder()
	mux.ServeHTTP(health, httptest.NewRequest(http.MethodGet, "/healthz", nil))
	if health.Code != http.StatusOK {
		t.Fatalf("healthz under load = %d, want 200", health.Code)
	}
}

func TestRateLimit(t *testing.T) {
	mux := Overload(NewMux(New(&fakeGateway{
		chatReply: modal.ChatResult{Reply: "ok"},
	})), 10, 0.000001, 1)
	post := func() *httptest.ResponseRecorder {
		rec := httptest.NewRecorder()
		mux.ServeHTTP(rec, httptest.NewRequest(
			http.MethodPost, "/api/v1/chat", strings.NewReader(`{"messages":[{"role":"user","content":"hi"}]}`)))
		return rec
	}

	if rec := post(); rec.Code != http.StatusOK {
		t.Fatalf("first request status = %d, want 200", rec.Code)
	}
	rec := post()
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("second request status = %d, want 429", rec.Code)
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("body is not JSON: %v", err)
	}
	errObj, _ := body["error"].(map[string]any)
	if errObj["code"] != "RATE_LIMITED" {
		t.Fatalf("code = %v, want RATE_LIMITED", errObj["code"])
	}
}

func TestVoice(t *testing.T) {
	validWav := base64.StdEncoding.EncodeToString([]byte("fake-wav-bytes"))

	tests := []struct {
		name       string
		body       string
		fake       *fakeGateway
		wantStatus int
		wantCode   string
		wantHeard  string
		wantAsr    string
	}{
		{
			name:       "text mode success",
			body:       `{"lang":"te","text":"హలో"}`,
			fake:       &fakeGateway{voiceOut: modal.VoiceResult{Heard: "హలో", Reply: "అవును అండి"}},
			wantStatus: http.StatusOK,
			wantHeard:  "హలో",
			wantAsr:    "whisper-small-hi-te-v2",
		},
		{
			name:       "audio mode success",
			body:       `{"lang":"hi","wav_b64":"` + validWav + `"}`,
			fake:       &fakeGateway{asrOut: "हलो", chatReply: modal.ChatResult{Reply: "हाँ बोलिए"}},
			wantStatus: http.StatusOK,
			wantHeard:  "हलो",
			wantAsr:    "whisper-small-hi-te-v2",
		},
		{
			name:       "default lang is hindi",
			body:       `{"text":"हलो"}`,
			fake:       &fakeGateway{voiceOut: modal.VoiceResult{Heard: "हलो"}},
			wantStatus: http.StatusOK,
			wantHeard:  "हलो",
			wantAsr:    "whisper-small-hi-te-v2",
		},
		{
			name:       "bad language rejected",
			body:       `{"lang":"en","text":"hello"}`,
			fake:       &fakeGateway{},
			wantStatus: http.StatusUnprocessableEntity,
			wantCode:   "VALIDATION_ERROR",
		},
		{
			name:       "neither audio nor text rejected",
			body:       `{"lang":"hi"}`,
			fake:       &fakeGateway{},
			wantStatus: http.StatusUnprocessableEntity,
			wantCode:   "VALIDATION_ERROR",
		},
		{
			name:       "bad base64 rejected",
			body:       `{"lang":"hi","wav_b64":"!!!not-base64!!!"}`,
			fake:       &fakeGateway{},
			wantStatus: http.StatusUnprocessableEntity,
			wantCode:   "VALIDATION_ERROR",
		},
		{
			name:       "upstream down maps to 502",
			body:       `{"lang":"te","text":"హలో"}`,
			fake:       &fakeGateway{asrErr: errors.New("connection refused")},
			wantStatus: http.StatusBadGateway,
			wantCode:   "UPSTREAM_ERROR",
		},
		{
			name:       "wrong method rejected",
			body:       ``,
			fake:       &fakeGateway{},
			wantStatus: http.StatusMethodNotAllowed,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			mux := NewMux(New(tt.fake))
			var req *http.Request
			if tt.name == "wrong method rejected" {
				req = httptest.NewRequest(http.MethodGet, "/api/v1/voice", nil)
			} else {
				req = httptest.NewRequest(http.MethodPost, "/api/v1/voice", strings.NewReader(tt.body))
			}
			rec := httptest.NewRecorder()
			mux.ServeHTTP(rec, req)

			if rec.Code != tt.wantStatus {
				t.Fatalf("status = %d, want %d (body: %s)", rec.Code, tt.wantStatus, rec.Body.String())
			}
			if tt.name == "wrong method rejected" {
				return
			}
			var body map[string]any
			if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
				t.Fatalf("body is not JSON: %v", err)
			}
			if tt.wantHeard != "" && body["heard"] != tt.wantHeard {
				t.Fatalf("heard = %v, want %q", body["heard"], tt.wantHeard)
			}
			if tt.wantAsr != "" && body["asr"] != tt.wantAsr {
				t.Fatalf("asr = %v, want %q", body["asr"], tt.wantAsr)
			}
			if tt.wantCode != "" {
				errObj, _ := body["error"].(map[string]any)
				if errObj["code"] != tt.wantCode {
					t.Fatalf("code = %v, want %q", errObj["code"], tt.wantCode)
				}
			}
		})
	}
}
