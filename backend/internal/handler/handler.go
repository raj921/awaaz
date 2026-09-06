package handler

import (
	"context"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"strings"
	"sync"
	"time"

	"awaaz/internal/apperror"
	"awaaz/internal/memory"
	"awaaz/internal/modal"
)

// modelGateway is the slice of the Modal client the handlers need. Defined on
// the consumer side (here, not in modal) — the Go-idiomatic placement.
type modelGateway interface {
	Chat(ctx context.Context, messages []modal.ChatMessage, maxTokens int) (modal.ChatResult, error)
	ChatVoice(ctx context.Context, heard string, maxTokens int) (modal.ChatResult, error)
	Voice(ctx context.Context, lang, wavB64, text string) (modal.VoiceResult, error)
	Asr(ctx context.Context, lang, wavB64, text string) (string, float64, error)
	Tts(ctx context.Context, text string) (string, float64, error)
}

// Compile-time proof that *modal.Client satisfies this consumer-side interface.
var _ modelGateway = (*modal.Client)(nil)

type Handler struct {
	gateway modelGateway
	sarvam  modelGateway
	mem     *memory.Client
	// allowedOrigins guards WebSocket upgrades. Browsers do not apply CORS
	// to WebSockets, so the room handler enforces the same allowlist itself.
	allowedOrigins []string
}

func New(gateway modelGateway) *Handler {
	return &Handler{
		gateway: gateway,
	}
}

// AllowOrigins sets the WebSocket origin allowlist (same list as CORS).
func (h *Handler) AllowOrigins(origins ...string) {
	cleaned := make([]string, 0, len(origins))
	for _, o := range origins {
		if o = strings.TrimSpace(o); o != "" {
			cleaned = append(cleaned, o)
		}
	}
	h.allowedOrigins = cleaned
}

// UseSarvam attaches the optional Sarvam provider. Without it, provider
// "sarvam" requests fail honestly instead of panicking on a nil gateway.
func (h *Handler) UseSarvam(gateway modelGateway) {
	h.sarvam = gateway
}

// UseMemory attaches the optional memory sidecar. Without it (or when the
// sidecar is down) chat simply runs without recalled context.
func (h *Handler) UseMemory(mem *memory.Client) {
	h.mem = mem
}

func NewMux(h *Handler) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", health)
	mux.HandleFunc("POST /api/v1/chat", h.chat)
	mux.HandleFunc("POST /api/v1/voice", h.voice)
	mux.HandleFunc("GET /api/v1/voice/session", h.voiceSession)
	mux.HandleFunc("POST /api/v1/warm", h.warm)
	mux.HandleFunc("GET /api/v1/memory", h.memoryList)
	mux.HandleFunc("POST /api/v1/memory", h.memoryAdd)
	mux.HandleFunc("POST /api/v1/memory/forget", h.memoryForget)
	return mux
}

// warmTimeout bounds the background warm probes.
const warmTimeout = 5 * time.Minute

// memoryTimeout bounds recall and capture. Memory sits on the critical path
// of every turn, so a wedged sidecar must cost a fraction of a second and
// then be ignored — never stall speech.
const memoryTimeout = 2 * time.Second

// warm preloads cold GPU containers (whisper, parler) in the background so
// the first real voice turn skips the 15–50 s model loads. Returns
// immediately; the loads keep running after the response.
func (h *Handler) warm(w http.ResponseWriter, r *http.Request) {
	if h.gateway == nil {
		respondError(w, apperror.NewBadGateway("gateway is not configured"))
		return
	}
	// The probe outlives the request (the point is to warm containers after
	// we have answered) but must still be bounded: the previous version
	// created a cancel func it never called, leaking the context and its
	// timer for the lifetime of the process on every warm call.
	probeCtx, cancel := context.WithTimeout(context.WithoutCancel(r.Context()), warmTimeout)
	var probes sync.WaitGroup
	probes.Add(2)
	go func() {
		defer probes.Done()
		_, _, _ = h.gateway.Asr(probeCtx, "auto", silentWavProbe, "")
	}()
	go func() {
		defer probes.Done()
		_, _, _ = h.gateway.Tts(probeCtx, "नमस्ते।")
	}()
	go func() {
		probes.Wait()
		cancel()
	}()
	w.WriteHeader(http.StatusNoContent)
}

// silentWavProbe is a 0.2 s silent 16 kHz mono WAV (base64): just enough
// audio to make asr_turn load whisper, cheap enough to be free.
var silentWavProbe = func() string {
	const headerLen, samples, sampleRate = 44, 3200, 16000
	wav := make([]byte, headerLen+samples*2)
	copy(wav, "RIFF")
	binary.LittleEndian.PutUint32(wav[4:], uint32(len(wav)-8))
	copy(wav[8:], "WAVEfmt ")
	binary.LittleEndian.PutUint32(wav[16:], 16)
	binary.LittleEndian.PutUint16(wav[20:], 1)
	binary.LittleEndian.PutUint16(wav[22:], 1)
	binary.LittleEndian.PutUint32(wav[24:], sampleRate)
	binary.LittleEndian.PutUint32(wav[28:], sampleRate*2)
	binary.LittleEndian.PutUint16(wav[32:], 2)
	binary.LittleEndian.PutUint16(wav[34:], 16)
	copy(wav[36:], "data")
	binary.LittleEndian.PutUint32(wav[40:], samples*2)
	return base64.StdEncoding.EncodeToString(wav)
}()

func health(w http.ResponseWriter, _ *http.Request) {
	respondJSON(w, http.StatusOK, map[string]string{
		"status": "ok",
	})
}

type chatMessageIn struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type chatRequestIn struct {
	Messages  []chatMessageIn `json:"messages"`
	MaxTokens int             `json:"max_tokens"`
	Provider  string          `json:"provider"`
}

func (h *Handler) chat(w http.ResponseWriter, r *http.Request) {
	var req chatRequestIn
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respondError(w, decodeError(err))
		return
	}
	if len(req.Messages) == 0 {
		respondError(w, apperror.NewUnprocessable("messages must not be empty"))
		return
	}
	messages := make([]modal.ChatMessage, 0, len(req.Messages))
	for _, m := range req.Messages {
		if m.Role == "" || m.Content == "" {
			respondError(w, apperror.NewUnprocessable("every message needs a role and content"))
			return
		}
		messages = append(messages, modal.ChatMessage{Role: m.Role, Content: m.Content})
	}
	maxTokens := req.MaxTokens
	if maxTokens == 0 {
		maxTokens = 50
	}
	if maxTokens < 1 || maxTokens > 200 {
		respondError(w, apperror.NewUnprocessable("max_tokens must be between 1 and 200"))
		return
	}

	gateway, model := h.gateway, "qwen3-1.7B+a2-bilingual"
	if req.Provider == "sarvam" {
		if h.sarvam == nil {
			respondError(w, apperror.NewBadGateway("sarvam provider is not configured"))
			return
		}
		gateway, model = h.sarvam, "sarvam-105b-conversations"
	}

	// Recall: last user turn retrieves memory context, sent as a system
	// message. Empty block (or sidecar down) leaves the messages untouched.
	lastUser := messages[len(messages)-1].Content
	recalled := h.recallFor(r.Context(), lastUser)
	if recalled.block != "" {
		messages = append([]modal.ChatMessage{{Role: "system", Content: recalled.block}}, messages...)
	}

	// Chat learns from conversation exactly like voice does. Without this,
	// the same sentence typed and spoken produced different memory state.
	//
	// Capture runs BEFORE the model call: what the user told us is true
	// whether or not the GPU answers, and losing a stated fact to an
	// upstream outage is the one failure a memory system must not have.
	captured := h.observe(r.Context(), lastUser)

	result, err := gateway.Chat(r.Context(), messages, maxTokens)
	if err != nil {
		respondError(w, mapUpstream(err))
		return
	}

	out := map[string]any{"reply": result.Reply, "model": model}
	if result.ServerMs > 0 {
		out["server_ms"] = result.ServerMs
	}
	if len(recalled.used) > 0 {
		out["memory_used"] = recalled.used
	}
	if len(captured) > 0 {
		out["memory_saved"] = captured
	}
	respondJSON(w, http.StatusOK, out)
}

type voiceRequestIn struct {
	Lang     string `json:"lang"`
	WavB64   string `json:"wav_b64"`
	Text     string `json:"text"`
	Provider string `json:"provider"`
	LLM      string `json:"llm"`
}

// asrModel names the tuned whisper build behind the voice endpoint. Bump on retrain.
const asrModel = "whisper-small-hi-te-v2"

func (h *Handler) voice(w http.ResponseWriter, r *http.Request) {
	var req voiceRequestIn
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respondError(w, decodeError(err))
		return
	}
	lang := req.Lang
	if lang == "" {
		lang = "auto"
	}
	if lang != "hi" && lang != "te" && lang != "auto" {
		respondError(w, apperror.NewUnprocessable("lang must be hi, te, or auto"))
		return
	}
	if req.WavB64 == "" && req.Text == "" {
		respondError(w, apperror.NewUnprocessable("send wav_b64 or text"))
		return
	}
	if req.WavB64 != "" {
		raw, err := base64.StdEncoding.DecodeString(req.WavB64)
		if err != nil || len(raw) == 0 || len(raw) > 2<<20 {
			respondError(w, apperror.NewUnprocessable("wav_b64 must be valid base64 under 2 MiB"))
			return
		}
	}

	// Full-Sarvam pipeline: one composed call.
	if req.Provider == "sarvam" {
		if h.sarvam == nil {
			respondError(w, apperror.NewBadGateway("sarvam provider is not configured"))
			return
		}
		result, err := h.sarvam.Voice(r.Context(), lang, req.WavB64, req.Text)
		if err != nil {
			respondError(w, mapUpstream(err))
			return
		}
		respondJSON(w, http.StatusOK, map[string]any{
			"heard": result.Heard, "reply": result.Reply,
			"asr": "saaras:v4", "audio_b64": result.AudioB64,
		})
		return
	}

	// Ours pipeline, stage-split: whisper → LLM (user's choice) → parler.
	heard, asrMs, err := h.gateway.Asr(r.Context(), lang, req.WavB64, req.Text)
	if err != nil {
		respondError(w, mapUpstream(err))
		return
	}
	llmGateway, model := h.gateway, "qwen3-1.7B+a2-bilingual"
	if req.LLM == "sarvam" {
		if h.sarvam == nil {
			respondError(w, apperror.NewBadGateway("sarvam provider is not configured"))
			return
		}
		llmGateway, model = h.sarvam, "sarvam-105b-conversations"
	}
	chat, err := llmGateway.Chat(r.Context(), []modal.ChatMessage{{Role: "user", Content: heard}}, 50)
	if err != nil {
		respondError(w, mapUpstream(err))
		return
	}
	audioB64, ttsMs, err := h.gateway.Tts(r.Context(), chat.Reply)
	if err != nil {
		respondError(w, mapUpstream(err))
		return
	}
	out := map[string]any{
		"heard": heard, "reply": chat.Reply,
		"asr": asrModel, "llm": model, "audio_b64": audioB64,
	}
	for key, ms := range map[string]float64{
		"asr_ms": asrMs, "llm_ms": chat.ServerMs, "tts_ms": ttsMs,
	} {
		if ms > 0 {
			out[key] = ms
		}
	}
	respondJSON(w, http.StatusOK, out)
}

// runVoiceTurn runs one voice turn (shared by the HTTP handler and the
// WebSocket room). Returns the response map including audio_b64, or an
// app error the caller translates for its transport.
func (h *Handler) runVoiceTurn(ctx context.Context, provider, llm, lang, wavB64, text string) (map[string]any, *apperror.AppError) {
	if provider == "sarvam" {
		if h.sarvam == nil {
			return nil, apperror.NewBadGateway("sarvam provider is not configured")
		}
		result, err := h.sarvam.Voice(ctx, lang, wavB64, text)
		if err != nil {
			return nil, mapUpstream(err)
		}
		return map[string]any{
			"heard": result.Heard, "reply": result.Reply,
			"asr": "saaras:v4", "audio_b64": result.AudioB64,
		}, nil
	}
	heard, asrMs, err := h.gateway.Asr(ctx, lang, wavB64, text)
	if err != nil {
		return nil, mapUpstream(err)
	}
	llmGateway, model := h.gateway, "qwen3-1.7B+a2-bilingual"
	if llm == "sarvam" {
		if h.sarvam == nil {
			return nil, apperror.NewBadGateway("sarvam provider is not configured")
		}
		llmGateway, model = h.sarvam, "sarvam-105b-conversations"
	}

	// Recall before answering. The voice path previously touched memory not
	// at all: the chat stage recalled context but a spoken turn never did, so
	// the assistant forgot your name the moment you talked to it instead of
	// typing. Same store, same guarantees, both surfaces.
	recalled := h.recallFor(ctx, heard)
	// Capture before the LLM for the same reason as chat: a transcribed
	// fact survives an upstream failure.
	captured := h.observe(ctx, heard)
	chat, err := llmGateway.ChatVoice(ctx, withMemory(heard, recalled.block), 50)
	if err != nil {
		return nil, mapUpstream(err)
	}
	// Spoken replies must be short and speakable: strip the markdown and
	// emoji a chat model emits, cut at a sentence end. The raw reply still
	// goes to the UI; only the TTS input is cleaned.
	spoken := cleanForTTS(chat.Reply)
	audioB64, ttsMs, err := h.gateway.Tts(ctx, spoken)
	if err != nil {
		return nil, mapUpstream(err)
	}
	out := map[string]any{
		"heard": heard, "reply": chat.Reply,
		"asr": asrModel, "llm": model, "audio_b64": audioB64,
	}
	for key, ms := range map[string]float64{
		"asr_ms": asrMs, "llm_ms": chat.ServerMs, "tts_ms": ttsMs,
	} {
		if ms > 0 {
			out[key] = ms
		}
	}
	if len(recalled.used) > 0 {
		out["memory_used"] = recalled.used
	}
	if len(captured) > 0 {
		out["memory_saved"] = captured
	}
	slog.Info("voice turn", "provider", provider, "llm", model,
		"heard", heard, "reply", firstLines(chat.Reply, 160),
		"spoken", firstLines(spoken, 160),
		"recalled", len(recalled.used), "captured", len(captured))
	return out, nil
}

// recallResult bundles the prompt block with the facts it came from.
type recallResult struct {
	block string
	used  []memory.Recalled
}

// recallFor fetches memory context. Memory is best-effort by design: a
// sidecar that is down or slow must degrade to a normal reply, never fail
// the turn.
func (h *Handler) recallFor(ctx context.Context, query string) recallResult {
	if h.mem == nil || strings.TrimSpace(query) == "" {
		return recallResult{}
	}
	memCtx, cancel := context.WithTimeout(ctx, memoryTimeout)
	defer cancel()
	block, used := h.mem.Recall(memCtx, query)
	return recallResult{block: block, used: used}
}

// observe offers the user's turn to the store for automatic capture.
func (h *Handler) observe(ctx context.Context, heard string) []memory.Fact {
	if h.mem == nil || strings.TrimSpace(heard) == "" {
		return nil
	}
	// Detached from the request context: capture must still complete when
	// the caller is a WebSocket turn that returns immediately after.
	obsCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), memoryTimeout)
	defer cancel()
	return h.mem.Observe(obsCtx, heard)
}

// withMemory prepends the recalled context to the spoken prompt. The voice
// model takes no system role, so the block rides inline.
func withMemory(heard, block string) string {
	if block == "" {
		return heard
	}
	return block + "\n\n" + heard
}

// firstLines truncates observability output — the log shows what was heard
// and answered, never unbounded blobs.
func firstLines(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}

// cleanForTTS strips chat formatting (markdown, emoji, extra whitespace) and
// cuts at a sentence end so the TTS speaks a complete thought instead of a
// truncated fragment.
func cleanForTTS(text string) string {
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
	fields := strings.Fields(b.String())
	clean := strings.Join(fields, " ")
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

func (h *Handler) memoryList(w http.ResponseWriter, r *http.Request) {
	if h.mem == nil {
		respondError(w, apperror.NewBadGateway("memory sidecar is not configured"))
		return
	}
	facts, err := h.mem.Facts(r.Context())
	if err != nil {
		respondError(w, apperror.NewBadGateway("memory sidecar is unreachable"))
		return
	}
	if facts == nil {
		facts = []memory.Fact{}
	}
	respondJSON(w, http.StatusOK, map[string]any{"facts": facts})
}

func (h *Handler) memoryAdd(w http.ResponseWriter, r *http.Request) {
	if h.mem == nil {
		respondError(w, apperror.NewBadGateway("memory sidecar is not configured"))
		return
	}
	var req struct {
		Text string `json:"text"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Text == "" {
		respondError(w, apperror.NewUnprocessable("text must not be empty"))
		return
	}
	fact, err := h.mem.Remember(r.Context(), req.Text)
	if err != nil {
		respondError(w, apperror.NewBadGateway("memory sidecar is unreachable"))
		return
	}
	respondJSON(w, http.StatusOK, map[string]any{"id": fact.ID, "text": fact.Text})
}

func (h *Handler) memoryForget(w http.ResponseWriter, r *http.Request) {
	if h.mem == nil {
		respondError(w, apperror.NewBadGateway("memory sidecar is not configured"))
		return
	}
	var req struct {
		Text string `json:"text"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Text == "" {
		respondError(w, apperror.NewUnprocessable("text must not be empty"))
		return
	}
	forgot, err := h.mem.Forget(r.Context(), req.Text)
	if err != nil {
		respondError(w, apperror.NewBadGateway("memory sidecar is unreachable"))
		return
	}
	respondJSON(w, http.StatusOK, map[string]any{"forgot": forgot})
}

// decodeError names the real failure: oversized bodies (past the middleware
// cap, usually a long recording) get an actionable message instead of the
// generic "invalid request body".
func decodeError(err error) *apperror.AppError {
	var tooLarge *http.MaxBytesError
	if errors.As(err, &tooLarge) {
		return apperror.NewBadRequest("request body too large, keep clips under 30 seconds")
	}
	return apperror.NewBadRequest("invalid request body")
}

func mapUpstream(err error) *apperror.AppError {
	if errors.Is(err, context.DeadlineExceeded) {
		return apperror.NewGatewayTimeout("model service took too long")
	}
	var upstream *modal.UpstreamError
	if errors.As(err, &upstream) && (upstream.Status == http.StatusTooManyRequests ||
		upstream.Status == http.StatusServiceUnavailable) {
		return apperror.NewServiceUnavailable("model service is busy, retry shortly")
	}
	return apperror.NewBadGateway("model service is unavailable")
}

func respondJSON(w http.ResponseWriter, status int, data any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(data)
}

func respondError(w http.ResponseWriter, err *apperror.AppError) {
	respondJSON(w, err.StatusCode, map[string]any{
		"error": map[string]any{
			"code":    err.Code,
			"message": err.Message,
		},
	})
}
