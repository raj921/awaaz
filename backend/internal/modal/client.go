package modal

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

const maxResponseBytes = 16 << 20

type UpstreamError struct {
	Status int
	Body   string
}

func (e *UpstreamError) Error() string {
	return fmt.Sprintf("upstream model service status %d: %s", e.Status, e.Body)
}

type Client struct {
	chatURL    string
	voiceURL   string
	asrURL     string
	ttsURL     string
	httpClient *http.Client
}

func NewClient(chatURL, voiceURL, asrURL, ttsURL string, timeout time.Duration) *Client {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.MaxIdleConns = 100
	transport.MaxIdleConnsPerHost = 100
	transport.IdleConnTimeout = 90 * time.Second
	return &Client{
		chatURL:    chatURL,
		voiceURL:   voiceURL,
		asrURL:     asrURL,
		ttsURL:     ttsURL,
		httpClient: &http.Client{Timeout: timeout, Transport: transport},
	}
}

type ChatMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type chatRequest struct {
	Messages  []ChatMessage `json:"messages"`
	MaxTokens int           `json:"max_tokens"`
}

type chatResponse struct {
	// Upstream calls the full reply "token" (one field regardless of length).
	Token    string  `json:"token"`
	ServerMs float64 `json:"server_ms"`
}

type ChatResult struct {
	Reply    string
	ServerMs float64
}

type voiceRequest struct {
	Lang   string `json:"lang"`
	WavB64 string `json:"wav_b64,omitempty"`
	Text   string `json:"text,omitempty"`
}

type voiceResponse struct {
	Heard    string  `json:"heard"`
	Reply    string  `json:"reply"`
	AsrMs    float64 `json:"asr_ms"`
	LlmMs    float64 `json:"llm_ms"`
	TtsMs    float64 `json:"tts_ms"`
	AudioB64 string  `json:"audio_b64"`
}

type VoiceResult struct {
	Heard    string
	Reply    string
	AsrMs    float64
	LlmMs    float64
	TtsMs    float64
	AudioB64 string
}

func (c *Client) Chat(ctx context.Context, messages []ChatMessage, maxTokens int) (ChatResult, error) {
	var out chatResponse
	if err := c.post(ctx, c.chatURL, chatRequest{Messages: messages, MaxTokens: maxTokens}, &out); err != nil {
		return ChatResult{}, err
	}
	return ChatResult{Reply: out.Token, ServerMs: out.ServerMs}, nil
}

// ChatVoice satisfies the gateway interface. The qwen continuation model
// takes no system prompt — it answers the user text as-is.
func (c *Client) ChatVoice(ctx context.Context, heard string, maxTokens int) (ChatResult, error) {
	return c.Chat(ctx, []ChatMessage{{Role: "user", Content: heard}}, maxTokens)
}

func (c *Client) Voice(ctx context.Context, lang, wavB64, text string) (VoiceResult, error) {
	var out voiceResponse
	body := voiceRequest{Lang: lang, WavB64: wavB64, Text: text}
	if err := c.post(ctx, c.voiceURL, body, &out); err != nil {
		return VoiceResult{}, err
	}
	return VoiceResult{
		Heard: out.Heard, Reply: out.Reply,
		AsrMs: out.AsrMs, LlmMs: out.LlmMs, TtsMs: out.TtsMs,
		AudioB64: out.AudioB64,
	}, nil
}

type asrResponse struct {
	Heard string  `json:"heard"`
	AsrMs float64 `json:"asr_ms"`
}

// Asr is the stage-split whisper endpoint: transcribe only.
func (c *Client) Asr(ctx context.Context, lang, wavB64, text string) (string, float64, error) {
	var out asrResponse
	body := voiceRequest{Lang: lang, WavB64: wavB64, Text: text}
	if err := c.post(ctx, c.asrURL, body, &out); err != nil {
		return "", 0, err
	}
	return out.Heard, out.AsrMs, nil
}

type ttsResponse struct {
	AudioB64 string  `json:"audio_b64"`
	TtsMs    float64 `json:"tts_ms"`
}

// Tts is the stage-split parler endpoint: synthesize only, one call.
// ponytail: an earlier two-way parallel split was reverted — Modal runs one
// input per container by default, so the "parallel" halves either queued
// behind each other or cold-started a second billed container. True overlap
// needs @modal.concurrent on tts_gen plus thread-safe generate; revisit
// only with warm-container measurements proving the win.
func (c *Client) Tts(ctx context.Context, text string) (string, float64, error) {
	var out ttsResponse
	if err := c.post(ctx, c.ttsURL, voiceRequest{Text: text}, &out); err != nil {
		return "", 0, err
	}
	return out.AudioB64, out.TtsMs, nil
}

func (c *Client) post(ctx context.Context, url string, payload, out any) error {
	raw, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("encode upstream request: %w", err)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(raw))
	if err != nil {
		return fmt.Errorf("build upstream request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("call upstream model service: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		snippet, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return &UpstreamError{Status: resp.StatusCode, Body: string(snippet)}
	}
	limited := io.LimitReader(resp.Body, maxResponseBytes)
	if err := json.NewDecoder(limited).Decode(out); err != nil {
		return fmt.Errorf("decode upstream response: %w", err)
	}
	_, _ = io.Copy(io.Discard, limited)
	return nil
}
