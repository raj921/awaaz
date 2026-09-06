// Command api runs the Awaaz gateway: a thin, stateless Go server in
// front of the Modal GPU workers (chat model + voice pipeline).
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"awaaz/internal/config"
	"awaaz/internal/handler"
	"awaaz/internal/memory"
	"awaaz/internal/modal"
	"awaaz/internal/sarvam"
)

func main() {
	cfg := config.FromEnv()
	client := modal.NewClient(cfg.ChatURL, cfg.VoiceURL, cfg.AsrURL, cfg.TtsURL, cfg.UpstreamTimeout)
	h := handler.New(client)
	if cfg.SarvamAPIKey != "" {
		h.UseSarvam(sarvam.NewClient(cfg.SarvamAPIKey, cfg.UpstreamTimeout))
	}
	h.UseMemory(memory.NewClient(cfg.MemoryURL))

	origins := splitOrigins(cfg.CORSOrigins)
	// The WebSocket room enforces the same allowlist itself: browsers do
	// not apply CORS to WebSocket upgrades.
	h.AllowOrigins(origins...)

	mux := handler.CORS(
		handler.Chain(
			handler.Overload(handler.NewMux(h), cfg.MaxInflight, cfg.RateLimitRPS, cfg.RateLimitBurst),
			cfg.MaxBodyBytes,
		),
		origins...,
	)

	server := &http.Server{
		Addr:    cfg.Addr,
		Handler: mux,
		// ReadHeaderTimeout, not ReadTimeout: a whole-request read deadline
		// also applies to a hijacked WebSocket, so it used to kill every
		// voice room a fixed time after it opened. WriteTimeout is off for
		// the same reason — long voice turns and streamed audio outlive any
		// fixed write budget, and per-connection deadlines are set by the
		// handlers that need them.
		ReadHeaderTimeout: 15 * time.Second,
		IdleTimeout:       120 * time.Second,
		ErrorLog:          slog.NewLogLogger(slog.Default().Handler(), slog.LevelWarn),
	}

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	done := make(chan struct{})
	go func() {
		<-stop
		slog.Info("shutting down")
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdownCtx)
		close(done)
	}()

	slog.Info("listening", "addr", cfg.Addr)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		slog.Error("server failed", "error", err)
		os.Exit(1)
	}
	<-done
	slog.Info("stopped")
}

// splitOrigins parses the comma-separated CORS_ORIGINS list, dropping the
// empty entries a trailing comma would otherwise turn into an origin that
// matches every request with no Origin header.
func splitOrigins(raw string) []string {
	parts := strings.Split(raw, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}
