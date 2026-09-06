// has a working default so `go run ./cmd/api` just works out of the box.
package config

import (
	"os"
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
}

func FromEnv() Config {
	return Config{
		Addr:            envOr("ADDR", ":8080"),
		ChatURL:         envOr("CHAT_URL", "https://raj315920--qwen3-a1-serve-first-token.modal.run"),
		VoiceURL:        envOr("VOICE_URL", "https://raj315920--voice-pipeline-voice-turn.modal.run"),
		AsrURL:          envOr("ASR_URL", "https://raj315920--voice-pipeline-asr-turn.modal.run"),
		TtsURL:          envOr("TTS_URL", "https://raj315920--voice-pipeline-tts-turn.modal.run"),
		SarvamAPIKey:    envOr("SARVAM_API_KEY", ""),
		MemoryURL:       envOr("MEMORY_URL", "http://127.0.0.1:18081"),
		CORSOrigins:     envOr("CORS_ORIGINS", "http://localhost:3000"),
		UpstreamTimeout: envDuration("UPSTREAM_TIMEOUT", 300*time.Second),
		MaxBodyBytes:    4 << 20,
	}
}

func envOr(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func envDuration(key string, fallback time.Duration) time.Duration {
	raw := os.Getenv(key)
	if raw == "" {
		return fallback
	}
	if parsed, err := time.ParseDuration(raw); err == nil {
		return parsed
	}
	return fallback
}
