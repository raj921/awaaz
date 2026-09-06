// Package config loads gateway settings from the environment. Every value
// has a working default so `go run ./cmd/api` just works out of the box.
package config

import (
	"log/slog"
	"os"
	"strconv"
	"time"
)

type Config struct {
	Addr            string
	ChatURL         string
	VoiceURL        string
	AsrURL          string
	TtsURL          string
	SarvamAPIKey    string
	MemoryURL       string
	CORSOrigins     string
	UpstreamTimeout time.Duration
	MaxBodyBytes    int64
	MaxInflight     int
	RateLimitRPS    float64
	RateLimitBurst  int
}

func FromEnv() Config {
	return Config{
		// Hosts inject PORT (Railway/Render/Heroku); ADDR wins when set
		// explicitly (Fly uses fly.toml's internal_port instead).
		Addr:            envOr("ADDR", ":"+envOr("PORT", "8080")),
		ChatURL:         envOr("CHAT_URL", "https://raj315920--qwen3-a1-serve-first-token.modal.run"),
		VoiceURL:        envOr("VOICE_URL", "https://raj315920--voice-pipeline-voice-turn.modal.run"),
		AsrURL:          envOr("ASR_URL", "https://raj315920--voice-pipeline-asr-turn.modal.run"),
		TtsURL:          envOr("TTS_URL", "https://raj315920--voice-pipeline-tts-turn.modal.run"),
		SarvamAPIKey:    envOr("SARVAM_API_KEY", ""),
		MemoryURL:       envOr("MEMORY_URL", "http://127.0.0.1:18081"),
		CORSOrigins:     envOr("CORS_ORIGINS", "http://localhost:3000"),
		UpstreamTimeout: envDuration("UPSTREAM_TIMEOUT", 300*time.Second),
		MaxBodyBytes:    envInt64("MAX_BODY_BYTES", 4<<20),
		MaxInflight:     envInt("MAX_INFLIGHT", 50),
		RateLimitRPS:    envFloat("RATE_LIMIT_RPS", 30),
		RateLimitBurst:  envInt("RATE_LIMIT_BURST", 60),
	}
}

func envOr(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

// envDuration parses a duration, warning loudly on a malformed value rather
// than silently falling back — a typo'd timeout that quietly reverts to the
// default is the kind of bug that only shows up under load.
func envDuration(key string, fallback time.Duration) time.Duration {
	raw := os.Getenv(key)
	if raw == "" {
		return fallback
	}
	parsed, err := time.ParseDuration(raw)
	if err != nil || parsed <= 0 {
		slog.Warn("invalid duration in environment, using default",
			"key", key, "value", raw, "default", fallback)
		return fallback
	}
	return parsed
}

func envInt(key string, fallback int) int {
	raw := os.Getenv(key)
	if raw == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(raw)
	if err != nil || parsed <= 0 {
		slog.Warn("invalid integer in environment, using default",
			"key", key, "value", raw, "default", fallback)
		return fallback
	}
	return parsed
}

func envInt64(key string, fallback int64) int64 {
	raw := os.Getenv(key)
	if raw == "" {
		return fallback
	}
	parsed, err := strconv.ParseInt(raw, 10, 64)
	if err != nil || parsed <= 0 {
		slog.Warn("invalid integer in environment, using default",
			"key", key, "value", raw, "default", fallback)
		return fallback
	}
	return parsed
}

func envFloat(key string, fallback float64) float64 {
	raw := os.Getenv(key)
	if raw == "" {
		return fallback
	}
	parsed, err := strconv.ParseFloat(raw, 64)
	if err != nil || parsed <= 0 {
		slog.Warn("invalid number in environment, using default",
			"key", key, "value", raw, "default", fallback)
		return fallback
	}
	return parsed
}
