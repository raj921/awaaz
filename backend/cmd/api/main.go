// Command api runs the AttuneBench gateway: a thin, stateless Go server in
// front of the Modal GPU workers (chat model + voice pipeline).
package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"attunebench/internal/config"
	"attunebench/internal/handler"
	"attunebench/internal/memory"
	"attunebench/internal/modal"
	"attunebench/internal/sarvam"
)

func main() {
	cfg := config.FromEnv()
	client := modal.NewClient(cfg.ChatURL, cfg.VoiceURL, cfg.AsrURL, cfg.TtsURL, cfg.UpstreamTimeout)
	h := handler.New(client)
	if cfg.SarvamAPIKey != "" {
		h.UseSarvam(sarvam.NewClient(cfg.SarvamAPIKey, cfg.UpstreamTimeout))
	}
	h.UseMemory(memory.NewClient(cfg.MemoryURL))
	mux := handler.CORS(handler.Chain(handler.Overload(handler.NewMux(h), 50, 30, 60), cfg.MaxBodyBytes), strings.Split(cfg.CORSOrigins, ",")...)

	server := &http.Server{
		Addr:         cfg.Addr,
		Handler:      mux,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 10 * time.Minute,
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
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		slog.Error("server failed", "error", err)
		os.Exit(1)
	}
	<-done
}
