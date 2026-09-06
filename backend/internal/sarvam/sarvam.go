// Package sarvam is a stdlib-only client for the Sarvam API (chat only).
// It speaks the OpenAI-compatible chat-completions shape and reuses the
// modal types so it satisfies the handler's modelGateway interface.
package sarvam

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"strings"
	"time"

	"awaaz/internal/modal"
)

const chatURL = "https://api.sarvam.ai/v1/chat/completions"

// Model is the dialogue-tuned chat model. Bump only for a named reason.
const Model = "sarvam-105b-conversations"

type Client struct {
	key        string
	httpClient *http.Client
}

func NewClient(apiKey string, timeout time.Duration) *Client {
	return &Client{key: apiKey, httpClient: &http.Client{Timeout: timeout}}
}

type sarvamMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type chatChoice struct {
	Message struct {
		Content string `json:"content"`
	} `json:"message"`
}

type chatResponse struct {
	Choices []chatChoice `json:"choices"`
}

// voiceSystem keeps spoken replies short and speakable: 1-2 sentences,
// user's language, plain text — the TTS stage cannot speak markdown.
const voiceSystem = "You are a voice assistant. Reply in 1-2 short sentences, " +
	"in the user's language, plain text only — no markdown, no emoji, " +
	"nothing that cannot be spoken aloud."

// ChatVoice answers for speaking: same chat model, voice-shaped output.
func (c *Client) ChatVoice(ctx context.Context, heard string, maxTokens int) (modal.ChatResult, error) {
	return c.chatWith(ctx, []modal.ChatMessage{
		{Role: "system", Content: voiceSystem},
		{Role: "user", Content: heard},
	}, maxTokens)
}
func (c *Client) Chat(ctx context.Context, messages []modal.ChatMessage, maxTokens int) (modal.ChatResult, error) {
	return c.chatWith(ctx, messages, maxTokens)
}

// chatWith is the shared completion call. ServerMs is always 0: Sarvam
// returns no server timing, and reporting our round-trip as server time
// would be a lie.
func (c *Client) chatWith(ctx context.Context, messages []modal.ChatMessage, maxTokens int) (modal.ChatResult, error) {
	in := make([]sarvamMessage, 0, len(messages))
	for _, m := range messages {
		in = append(in, sarvamMessage{Role: m.Role, Content: m.Content})
	}
	raw, err := json.Marshal(map[string]any{
		"model": Model, "messages": in, "max_tokens": maxTokens,
	})
	if err != nil {
		return modal.ChatResult{}, fmt.Errorf("encode sarvam request: %w", err)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, chatURL, bytes.NewReader(raw))
	if err != nil {
		return modal.ChatResult{}, fmt.Errorf("build sarvam request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+c.key)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return modal.ChatResult{}, fmt.Errorf("call sarvam: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		snippet, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return modal.ChatResult{}, &modal.UpstreamError{Status: resp.StatusCode, Body: string(snippet)}
	}
	var out chatResponse
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&out); err != nil {
		return modal.ChatResult{}, fmt.Errorf("decode sarvam response: %w", err)
	}
	if len(out.Choices) == 0 {
		return modal.ChatResult{}, fmt.Errorf("sarvam returned no choices")
	}
	return modal.ChatResult{Reply: out.Choices[0].Message.Content}, nil
}

// Voice runs the full Sarvam loop: Saaras STT (or text direct) → Sarvam chat
// → Bulbul TTS. Stage timings stay 0 — Sarvam reports none, and the handler
// omits zero timings rather than relabeling our round-trip as server time.
func (c *Client) Voice(ctx context.Context, lang, wavB64, text string) (modal.VoiceResult, error) {
	heard := text
	detected := ""
	if heard == "" {
		raw, err := base64.StdEncoding.DecodeString(wavB64)
		if err != nil {
			return modal.VoiceResult{}, fmt.Errorf("decode clip: %w", err)
		}
		heard, detected, err = c.Transcribe(ctx, raw)
		if err != nil {
			return modal.VoiceResult{}, err
		}
	}
	chat, err := c.ChatVoice(ctx, heard, 50)
	if err != nil {
		return modal.VoiceResult{}, err
	}
	langCode := "hi-IN"
	if lang == "te" || detected == "te-IN" {
		langCode = "te-IN"
	}
	wav, err := c.Synthesize(ctx, speakable(chat.Reply), langCode)
	if err != nil {
		return modal.VoiceResult{}, err
	}
	return modal.VoiceResult{
		Heard: heard, Reply: chat.Reply,
		AudioB64: base64.StdEncoding.EncodeToString(wav),
	}, nil
}

// Asr satisfies the gateway's stage-split interface: Saaras transcribes.
func (c *Client) Asr(ctx context.Context, lang, wavB64, text string) (string, float64, error) {
	if text != "" {
		return text, 0, nil
	}
	raw, err := base64.StdEncoding.DecodeString(wavB64)
	if err != nil {
		return "", 0, fmt.Errorf("decode clip: %w", err)
	}
	start := time.Now()
	heard, _, err := c.Transcribe(ctx, raw)
	return heard, elapsedMs(start), err
}

// Tts satisfies the gateway's stage-split interface: Bulbul speaks.
func (c *Client) Tts(ctx context.Context, text string) (string, float64, error) {
	start := time.Now()
	langCode := "hi-IN"
	wav, err := c.Synthesize(ctx, text, langCode)
	if err != nil {
		return "", 0, err
	}
	return base64.StdEncoding.EncodeToString(wav), elapsedMs(start), nil
}

func elapsedMs(start time.Time) float64 {
	return float64(time.Since(start).Milliseconds())
}

// speakable strips chat formatting (markdown, emoji, extra whitespace) and
// cuts at a sentence end so Bulbul speaks a complete thought. Mirrors the
// handler's cleanForTTS for the parler path — the two stay in lockstep.
func speakable(text string) string {
	var b strings.Builder
	for _, r := range text {
		switch {
		case r == '*' || r == '#' || r == '_' || r == '`' || r == '>':
			continue
		case r >= 0x1F300 && r <= 0x1FAFF, r >= 0x2600 && r <= 0x27BF,
			r == 0xFE0F || r == 0x200D:
			continue
		default:
			b.WriteRune(r)
		}
	}
	clean := strings.Join(strings.Fields(b.String()), " ")
	const maxRunes = 200
	runes := []rune(clean)
	if len(runes) <= maxRunes {
		return clean
	}
	for i := maxRunes - 1; i > maxRunes/2; i-- {
		if runes[i] == '।' || runes[i] == '.' || runes[i] == '?' || runes[i] == '!' {
			return string(runes[:i+1])
		}
	}
	return string(runes[:maxRunes])
}

type sttResponse struct {
	Transcript   string `json:"transcript"`
	LanguageCode string `json:"language_code"`
}

// Transcribe sends raw WAV bytes to Saaras. Clips must be ≤30 s (sync API limit).
// Returns the transcript and the detected BCP-47 code ("" if none).
func (c *Client) Transcribe(ctx context.Context, wav []byte) (string, string, error) {
	var body bytes.Buffer
	w := multipart.NewWriter(&body)
	_ = w.WriteField("model", "saaras:v4")
	_ = w.WriteField("mode", "transcribe")
	fw, err := w.CreateFormFile("file", "clip.wav")
	if err != nil {
		return "", "", fmt.Errorf("build saaras upload: %w", err)
	}
	if _, err := fw.Write(wav); err != nil {
		return "", "", fmt.Errorf("build saaras upload: %w", err)
	}
	if err := w.Close(); err != nil {
		return "", "", fmt.Errorf("build saaras upload: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, "https://api.sarvam.ai/speech-to-text", &body)
	if err != nil {
		return "", "", fmt.Errorf("build saaras request: %w", err)
	}
	req.Header.Set("Content-Type", w.FormDataContentType())
	req.Header.Set("api-subscription-key", c.key)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return "", "", fmt.Errorf("call saaras: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		snippet, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return "", "", &modal.UpstreamError{Status: resp.StatusCode, Body: string(snippet)}
	}
	var out sttResponse
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&out); err != nil {
		return "", "", fmt.Errorf("decode saaras response: %w", err)
	}
	return out.Transcript, out.LanguageCode, nil
}

type ttsResponse struct {
	Audios []string `json:"audios"`
}

// Synthesize speaks text with Bulbul v3 and returns raw WAV bytes.
// ponytail: fixed male voice + default pace, speaker/pace params when the UI asks.
func (c *Client) Synthesize(ctx context.Context, text, langCode string) ([]byte, error) {
	raw, err := json.Marshal(map[string]any{
		"text": text, "language_code": langCode,
		"speaker": "shubh", "model": "bulbul:v3",
	})
	if err != nil {
		return nil, fmt.Errorf("encode bulbul request: %w", err)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, "https://api.sarvam.ai/text-to-speech", bytes.NewReader(raw))
	if err != nil {
		return nil, fmt.Errorf("build bulbul request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("api-subscription-key", c.key)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("call bulbul: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		snippet, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return nil, &modal.UpstreamError{Status: resp.StatusCode, Body: string(snippet)}
	}
	var out ttsResponse
	if err := json.NewDecoder(io.LimitReader(resp.Body, 4<<20)).Decode(&out); err != nil {
		return nil, fmt.Errorf("decode bulbul response: %w", err)
	}
	if len(out.Audios) == 0 || out.Audios[0] == "" {
		return nil, fmt.Errorf("bulbul returned no audio")
	}
	wav, err := base64.StdEncoding.DecodeString(out.Audios[0])
	if err != nil {
		return nil, fmt.Errorf("decode bulbul audio: %w", err)
	}
	return wav, nil
}
