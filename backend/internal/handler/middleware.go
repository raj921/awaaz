package handler

import (
	"bufio"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"sync"
	"time"

	"awaaz/internal/apperror"
)

// CORS allows browser frontends to call the API. Origins come from config
// (CORS_ORIGINS, comma-separated) — localhost by default, the hosted UI
// origin in production. ponytail: exact-match allowlist, no credentials,
// no per-route rules until a second consumer needs them.
func CORS(next http.Handler, origins ...string) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		for _, o := range origins {
			if o != "" && origin == o {
				w.Header().Set("Access-Control-Allow-Origin", origin)
				w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
				w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
				break
			}
		}
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// Chain applies request-scoped middleware: an ID for tracing, panic recovery,
// an upstream-safe body cap, and per-request logging.
func Chain(next http.Handler, maxBodyBytes int64) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := newRequestID()
		r.Body = http.MaxBytesReader(w, r.Body, maxBodyBytes)

		rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		start := time.Now()
		defer func() {
			if recovered := recover(); recovered != nil {
				slog.Error("panic recovered", "request_id", id, "panic", recovered)
				if !rec.wroteHeader {
					http.Error(rec.ResponseWriter, "internal error", http.StatusInternalServerError)
					rec.status = http.StatusInternalServerError
				}
			}
			slog.Info("request",
				"request_id", id,
				"method", r.Method,
				"path", r.URL.Path,
				"status", rec.status,
				"duration_ms", time.Since(start).Milliseconds(),
			)
		}()
		next.ServeHTTP(rec, r)
	})
}

func newRequestID() string {
	var raw [8]byte
	if _, err := rand.Read(raw[:]); err != nil {
		return "unknown"
	}
	return hex.EncodeToString(raw[:])
}

type statusRecorder struct {
	http.ResponseWriter
	status      int
	wroteHeader bool
}

// Hijack delegates so the WebSocket room can take over the connection —
// the embedded interface alone only promotes Header/Write/WriteHeader.
func (s *statusRecorder) Hijack() (net.Conn, *bufio.ReadWriter, error) {
	hijacker, ok := s.ResponseWriter.(http.Hijacker)
	if !ok {
		return nil, nil, errors.New("hijack unsupported by underlying writer")
	}
	return hijacker.Hijack()
}

func (s *statusRecorder) WriteHeader(status int) {
	if s.wroteHeader {
		return
	}
	s.wroteHeader = true
	s.status = status
	s.ResponseWriter.WriteHeader(status)
}

// bucket is one client's token bucket. Idle entries are never evicted —
// acceptable at our scale, noted as the first thing to fix past it.
type bucket struct {
	tokens  float64
	updated time.Time
}

// Overload sheds load instead of crashing: at most maxInflight API requests
// run at once (excess gets 503), and each client IP refills rps tokens/sec up
// to burst (excess gets 429). /healthz always answers, even under load.
func Overload(next http.Handler, maxInflight int, rps float64, burst int) http.Handler {
	sem := make(chan struct{}, maxInflight)
	var mu sync.Mutex
	limiters := map[string]*bucket{}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/healthz" {
			next.ServeHTTP(w, r)
			return
		}
		select {
		case sem <- struct{}{}:
			defer func() { <-sem }()
		default:
			respondError(w, apperror.NewServiceUnavailable("server busy, retry shortly"))
			return
		}
		ip, _, _ := net.SplitHostPort(r.RemoteAddr)
		mu.Lock()
		b, ok := limiters[ip]
		if !ok {
			b = &bucket{tokens: float64(burst), updated: time.Now()}
			limiters[ip] = b
		}
		now := time.Now()
		b.tokens = min(float64(burst), b.tokens+now.Sub(b.updated).Seconds()*rps)
		b.updated = now
		allowed := b.tokens >= 1
		if allowed {
			b.tokens--
		}
		mu.Unlock()
		if !allowed {
			respondError(w, apperror.NewTooManyRequests("rate limit exceeded, slow down"))
			return
		}
		next.ServeHTTP(w, r)
	})
}
