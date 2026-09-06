package handler

// Voice room: one WebSocket = one session ("room"). Audio streams up as raw
// PCM16LE mono 16 kHz binary frames; the server runs end-of-speech VAD,
// flushes each turn through the voice pipeline, and pushes the reply text
// plus audio back on the same socket. The mic never closes during a room.
//
// ponytail: no barge-in (speech during "thinking" is dropped), one user per
// room; interruptible turns need a streaming ASR stage first.

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"log/slog"
	"math"
	"net/http"
	"sync"
	"time"

	"awaaz/internal/apperror"
)

const (
	vadSpeechRMS = 0.02 // ~peak 0.06, matching the old client-side detector
	vadSilence   = 1600 * time.Millisecond
	minTurnBytes = 8000  // 250 ms of 16 kHz PCM — shorter bursts are noise
	maxTurnBytes = 80000 // 25 s — whisper's comfortable ceiling

	// pingInterval keeps the socket alive through proxies and load
	// balancers, which silently drop idle connections after 30–60 s. A room
	// where the user thinks before speaking is idle by definition, so
	// without this the socket "connects" and then quietly stops listening.
	pingInterval = 20 * time.Second
	// readIdleTimeout ends a room whose client has gone away without a
	// close frame. Comfortably larger than pingInterval so a healthy but
	// silent client is never dropped.
	readIdleTimeout = 90 * time.Second
	// writeTimeout bounds a single frame write to a stalled client.
	writeTimeout = 20 * time.Second
	// turnTimeout bounds one full ASR→LLM→TTS pipeline run.
	turnTimeout = 5 * time.Minute
)

func (h *Handler) voiceSession(w http.ResponseWriter, r *http.Request) {
	key, err := checkUpgrade(r)
	if err != nil {
		respondError(w, apperror.NewBadRequest(err.Error()))
		return
	}
	// Browsers do not apply CORS to WebSockets: without an Origin check any
	// website could silently open a room against this gateway.
	if !originAllowed(r.Header.Get("Origin"), h.allowedOrigins) {
		respondError(w, apperror.NewForbidden("origin not allowed"))
		return
	}
	hij, ok := w.(http.Hijacker)
	if !ok {
		respondError(w, apperror.NewBadGateway("connection hijacking unsupported"))
		return
	}
	conn, brw, err := hij.Hijack()
	if err != nil {
		respondError(w, apperror.NewBadGateway("hijack failed"))
		return
	}
	defer conn.Close()

	// The server's ReadTimeout/WriteTimeout deadlines are still armed on the
	// hijacked connection. Leaving them in place kills every room a fixed
	// number of seconds after it opens — the socket connects, then stops
	// receiving audio for no visible reason. Clear them and manage
	// deadlines per read/write from here on.
	_ = conn.SetDeadline(time.Time{})

	provider := r.URL.Query().Get("provider")
	llm := r.URL.Query().Get("llm")
	lang := r.URL.Query().Get("lang")
	if lang != "hi" && lang != "te" {
		lang = "auto"
	}

	if err := wsUpgrade(brw, key); err != nil {
		return
	}
	if err := brw.Flush(); err != nil {
		return
	}
	ws := &wsConn{conn: conn, br: brw.Reader, writeTimeout: writeTimeout}

	// The room outlives the HTTP request semantics, but must still stop when
	// the process shuts down; WithoutCancel keeps the values (trace ids) and
	// drops the cancellation tied to the handler returning.
	ctx, cancel := context.WithCancel(context.WithoutCancel(r.Context()))
	defer cancel()

	var room [4]byte
	if _, err := rand.Read(room[:]); err != nil {
		ws.writeClose(closeInternalError, "room id failed")
		return
	}
	roomID := hex.EncodeToString(room[:])

	// send is called from the read loop and (for state) from the keepalive
	// goroutine, so marshalling errors are surfaced rather than swallowed.
	send := func(v any) {
		raw, err := json.Marshal(v)
		if err != nil {
			slog.Error("voice room encode failed", "room", roomID, "error", err)
			return
		}
		if err := ws.write(opText, raw); err != nil {
			slog.Debug("voice room write failed", "room", roomID, "error", err)
		}
	}
	send(map[string]string{"type": "room", "id": "r-" + roomID})
	send(map[string]string{"type": "state", "value": "listening"})
	slog.Info("voice room opened", "room", roomID, "provider", provider, "llm", llm)

	// Keepalive: pings on an interval, stopped when the room ends. Without
	// it an idle room is reaped by the first proxy in the path.
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		ticker := time.NewTicker(pingInterval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				if err := ws.ping(); err != nil {
					// The read loop will observe the same failure and exit.
					return
				}
			}
		}
	}()
	defer wg.Wait()

	s := &roomState{
		h: h, ws: ws, ctx: ctx, send: send, roomID: roomID,
		provider: provider, llm: llm, lang: lang,
		lastLoud: time.Now(),
	}

	for {
		// A per-read deadline detects a vanished client. It is refreshed on
		// every frame, including the pongs our keepalive provokes.
		if err := conn.SetReadDeadline(time.Now().Add(readIdleTimeout)); err != nil {
			break
		}
		op, payload, err := ws.nextMessage()
		if err != nil {
			if !errors.Is(err, errClosed) {
				code, reason := closeCodeFor(err)
				ws.writeClose(code, reason)
				slog.Info("voice room read ended", "room", roomID, "error", err)
			}
			break
		}
		switch op {
		case opText:
			if stop := s.handleControl(payload); stop {
				ws.writeClose(closeNormal, "")
				slog.Info("voice room closed", "room", roomID)
				return
			}
		case opBinary:
			s.handleAudio(payload)
		}
	}
	slog.Info("voice room ended", "room", roomID)
}

// roomState is one room's mutable state. Extracting it keeps voiceSession a
// readable transport loop instead of a 150-line closure over ten variables.
type roomState struct {
	h      *Handler
	ws     *wsConn
	ctx    context.Context
	send   func(any)
	roomID string

	provider string
	llm      string
	lang     string

	turn     []byte
	spoke    bool
	lastLoud time.Time
	thinking bool
	// echoguardUntil: after the reply audio goes out, incoming audio is the
	// user's speakers feeding back into their mic — drop it until the
	// client reports playback finished ("played"), or the reply length
	// plus a margin elapses.
	echoguardUntil time.Time
	// hold: while the client holds the button, silence never flushes — only
	// release ("flush") or the 25 s cap ends the turn. Hands-free tap mode
	// keeps the VAD behavior.
	hold bool
}

type controlMessage struct {
	Type     string `json:"type"`
	Provider string `json:"provider"`
	LLM      string `json:"llm"`
	Lang     string `json:"lang"`
	Active   bool   `json:"active"`
}

// handleControl processes one JSON control frame. Returns true when the
// client asked to end the room.
func (s *roomState) handleControl(payload []byte) (stop bool) {
	var msg controlMessage
	if err := json.Unmarshal(payload, &msg); err != nil {
		s.send(map[string]string{"type": "error", "message": "malformed control message"})
		return false
	}
	switch msg.Type {
	case "config":
		if msg.Provider != "" {
			s.provider = msg.Provider
		}
		if msg.LLM != "" {
			s.llm = msg.LLM
		}
		if msg.Lang == "hi" || msg.Lang == "te" || msg.Lang == "auto" {
			s.lang = msg.Lang
		}

	case "played":
		s.echoguardUntil = time.Time{}
		s.lastLoud = time.Now()

	case "hold":
		s.hold = msg.Active
		if msg.Active {
			// Starting to hold begins a fresh turn. Without this reset the
			// buffer still holds whatever leaked in before the press, and
			// `lastLoud` is stale enough that the very first audio frame
			// after release looks like 1.6 s of silence — the turn gets
			// flushed or dropped before the user finishes their first word.
			s.turn, s.spoke = nil, false
			s.lastLoud = time.Now()
			s.echoguardUntil = time.Time{}
		}

	case "flush":
		s.hold = false
		if !s.thinking {
			s.flushTurn("push")
		}

	case "stop":
		s.send(map[string]string{"type": "state", "value": "ended"})
		return true

	default:
		s.send(map[string]string{"type": "error", "message": "unknown message type"})
	}
	return false
}

// handleAudio buffers one PCM frame and applies the VAD.
func (s *roomState) handleAudio(payload []byte) {
	if s.thinking || time.Now().Before(s.echoguardUntil) {
		return // no barge-in; echo guard while the reply plays out
	}
	// PCM16 frames are pairs of bytes. An odd length means a truncated or
	// mis-encoded frame; appending it shifts every subsequent sample by one
	// byte and turns the rest of the turn into white noise.
	if len(payload)%2 != 0 {
		payload = payload[:len(payload)-1]
	}
	if len(payload) == 0 {
		return
	}
	// Cap the buffer before appending so a client that ignores the flush
	// cannot grow it without bound.
	if len(s.turn)+len(payload) > maxTurnBytes {
		payload = payload[:maxTurnBytes-len(s.turn)]
	}
	s.turn = append(s.turn, payload...)
	if pcmRMS(payload) > vadSpeechRMS {
		s.spoke = true
		s.lastLoud = time.Now()
	}
	silent := time.Since(s.lastLoud) > vadSilence
	switch {
	case len(s.turn) >= maxTurnBytes:
		s.flushTurn("max")
	case s.spoke && silent && !s.hold:
		s.flushTurn("silence")
	}
}

// flushTurn runs the accumulated audio through the pipeline. Reason is
// logged with the turn length for VAD tuning ("silence", "max", "push").
func (s *roomState) flushTurn(reason string) {
	secs := float64(len(s.turn)) / bytesPerSecond
	if len(s.turn) < minTurnBytes || !s.spoke {
		// Silence never speaks: reset the buffer WITHOUT running the
		// pipeline — an idle mic must not trigger phantom turns, and a
		// sub-word burst is not a turn yet.
		slog.Info("voice turn dropped", "room", s.roomID,
			"reason", "too-short-or-silent", "seconds", secs)
		s.turn, s.spoke = nil, false
		s.lastLoud = time.Now()
		return
	}
	s.thinking = true
	s.send(map[string]string{"type": "state", "value": "thinking"})
	slog.Info("voice turn flush", "room", s.roomID, "reason", reason, "seconds", secs)

	wav := buildWav(s.turn)
	s.turn, s.spoke = nil, false

	// Bound the pipeline: without a deadline a wedged upstream pins the
	// room in "thinking" forever and the user can never speak again.
	turnCtx, cancel := context.WithTimeout(s.ctx, turnTimeout)
	result, appErr := s.h.runVoiceTurn(turnCtx, s.provider, s.llm, s.lang, wav, "")
	cancel()

	// Always leave "thinking" — every return path below re-opens the mic.
	defer func() {
		s.thinking = false
		s.lastLoud = time.Now()
		s.send(map[string]string{"type": "state", "value": "listening"})
	}()

	if appErr != nil {
		s.send(map[string]string{"type": "error", "message": appErr.Message})
		return
	}
	audioB64, _ := result["audio_b64"].(string)
	delete(result, "audio_b64")
	// Tag the frame: every other message on this socket is discriminated by
	// "type", and the client switches on it. Without this the turn result
	// arrived as an untyped blob and the transcript never rendered — the
	// reply text was silently dropped by the UI.
	result["type"] = "reply"
	s.send(result)

	audio, err := base64.StdEncoding.DecodeString(audioB64)
	if err != nil || len(audio) == 0 {
		// Text reply already delivered; only the audio is missing.
		if err != nil {
			slog.Warn("voice reply audio undecodable", "room", s.roomID, "error", err)
		}
		return
	}
	s.send(map[string]string{"type": "state", "value": "speaking"})
	if err := s.ws.write(opBinary, audio); err != nil {
		slog.Debug("voice reply audio write failed", "room", s.roomID, "error", err)
		return
	}
	// Echo guard sized to the reply: audio length + margin, released early
	// by the client's "played". A fixed window would deafen long replies or
	// linger after short ones.
	playSecs := math.Max(0, float64(len(audio)-wavHeaderLen)/bytesPerSecond)
	s.echoguardUntil = time.Now().Add(
		time.Duration(playSecs*float64(time.Second)) + 4*time.Second)
}

const (
	sampleRate     = 16000
	wavHeaderLen   = 44
	bytesPerSecond = sampleRate * 2 // mono PCM16
)

// pcmRMS returns the root-mean-square of a PCM16LE buffer, normalized 0..1.
func pcmRMS(pcm []byte) float64 {
	samples := len(pcm) / 2
	if samples == 0 {
		return 0
	}
	var sum float64
	for i := 0; i+1 < len(pcm); i += 2 {
		v := float64(int16(binary.LittleEndian.Uint16(pcm[i:]))) / 32768
		sum += v * v
	}
	return math.Sqrt(sum / float64(samples))
}

// buildWav wraps raw PCM16LE mono 16 kHz in a WAV header and base64s it.
func buildWav(pcm []byte) string {
	wav := make([]byte, wavHeaderLen+len(pcm))
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
	binary.LittleEndian.PutUint32(wav[40:], uint32(len(pcm)))
	copy(wav[wavHeaderLen:], pcm)
	return base64.StdEncoding.EncodeToString(wav)
}
