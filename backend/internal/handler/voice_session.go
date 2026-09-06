package handler

// Voice room: one WebSocket = one session ("room"). Audio streams up as raw
// PCM16LE mono 16 kHz binary frames; the server runs end-of-speech VAD,
// flushes each turn through the voice pipeline, and pushes the reply text
// plus audio back on the same socket. The mic never closes during a room.
//
// ponytail: no barge-in (speech during "thinking" is dropped), one user per
// room; interruptible turns need a streaming ASR stage first.

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"log/slog"
	"math"
	"net/http"
	"time"

	"attunebench/internal/apperror"
)

const (
	vadSpeechRMS = 0.02 // ~peak 0.06, matching the old client-side detector
	vadSilence   = 1600 * time.Millisecond
	minTurnBytes = 8000  // 250 ms of 16 kHz PCM — shorter bursts are noise
	maxTurnBytes = 80000 // 25 s — whisper's comfortable ceiling
)

func (h *Handler) voiceSession(w http.ResponseWriter, r *http.Request) {
	key := r.Header.Get("Sec-WebSocket-Key")
	if key == "" || r.Header.Get("Upgrade") != "websocket" {
		respondError(w, apperror.NewBadRequest("websocket upgrade required"))
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

	provider := r.URL.Query().Get("provider")
	llm := r.URL.Query().Get("llm")
	if err := wsUpgrade(nil, brw, key); err != nil {
		return
	}
	brw.Flush()
	ws := &wsConn{conn: conn, br: brw.Reader}

	var room [4]byte
	_, _ = rand.Read(room[:])
	send := func(v any) {
		raw, _ := json.Marshal(v)
		_ = ws.write(0x1, raw)
	}
	send(map[string]string{"type": "room", "id": "r-" + hex.EncodeToString(room[:])})
	send(map[string]string{"type": "state", "value": "listening"})
	slog.Info("voice room opened", "room", hex.EncodeToString(room[:]), "provider", provider, "llm", llm)

	var (
		turn     []byte
		spoke    bool
		lastLoud = time.Now()
		thinking bool
		// Echo guard: after the reply audio goes out, incoming audio is the
		// user's speakers feeding back into their mic — drop it until the
		// client reports playback finished ("played"), or 20 s as a fallback.
		echoguardUntil time.Time
		// Push-to-talk: while the client holds the button, silence never
		// flushes — only release ("flush") or the 25 s cap ends the turn.
		// Hands-free tap mode keeps the VAD behavior below.
		hold bool
	)
	// flushTurn runs the accumulated audio through the pipeline. Reason is
	// logged with the turn length for VAD tuning ("silence", "max", "push").
	flushTurn := func(reason string) {
		secs := float64(len(turn)) / 32000
		if len(turn) < minTurnBytes || !spoke {
			// Silence never speaks: reset the buffer WITHOUT running the
			// pipeline — an idle mic must not trigger phantom turns, and a
			// sub-word burst is not a turn yet.
			slog.Info("voice turn dropped", "reason", "too-short-or-silent", "seconds", secs)
			turn, spoke = nil, false
			return
		}
		thinking = true
		send(map[string]string{"type": "state", "value": "thinking"})
		slog.Info("voice turn flush", "reason", reason, "seconds", secs)
		result, appErr := h.runVoiceTurn(r.Context(), provider, llm, "auto", buildWav(turn), "")
		turn, spoke = nil, false
		if appErr != nil {
			thinking = false
			send(map[string]string{"type": "error", "message": appErr.Message})
			send(map[string]string{"type": "state", "value": "listening"})
			return
		}
		audioB64, _ := result["audio_b64"].(string)
		delete(result, "audio_b64")
		send(result)
		send(map[string]string{"type": "state", "value": "speaking"})
		if wav, err := base64.StdEncoding.DecodeString(audioB64); err == nil {
			_ = ws.write(0x2, wav)
			// Echo guard sized to the reply: audio length + margin,
			// released early by the client's "played". A fixed window
			// would deafen long replies or linger after short ones.
			secs := float64(len(wav)-44) / 32000
			echoguardUntil = time.Now().Add(
				time.Duration(secs*float64(time.Second)) + 4*time.Second)
		}
		thinking = false
		send(map[string]string{"type": "state", "value": "listening"})
		lastLoud = time.Now()
	}
	for {
		op, payload, err := ws.nextFrame()
		if err != nil {
			break
		}
		switch op {
		case 0x1:
			var msg struct {
				Type     string `json:"type"`
				Provider string `json:"provider"`
				LLM      string `json:"llm"`
				Active   bool   `json:"active"`
			}
			if json.Unmarshal(payload, &msg) != nil {
				continue
			}
			switch msg.Type {
			case "config":
				if msg.Provider != "" {
					provider = msg.Provider
				}
				if msg.LLM != "" {
					llm = msg.LLM
				}
			case "played":
				echoguardUntil = time.Time{}
				lastLoud = time.Now()
			case "hold":
				hold = msg.Active
			case "flush":
				hold = false
				if !thinking {
					flushTurn("push")
				}
			case "stop":
				send(map[string]string{"type": "state", "value": "ended"})
				slog.Info("voice room closed", "room", hex.EncodeToString(room[:]))
				return
			}

		case 0x2:
			if thinking || time.Now().Before(echoguardUntil) {
				continue // no barge-in; echo guard while the reply plays out
			}
			turn = append(turn, payload...)
			if pcmRMS(payload) > vadSpeechRMS {
				spoke = true
				lastLoud = time.Now()
			}
			silent := time.Since(lastLoud) > vadSilence
			if len(turn) >= maxTurnBytes {
				flushTurn("max")
			} else if spoke && silent && !hold {
				flushTurn("silence")
			}
		}
	}
}

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
	const headerLen, sampleRate = 44, 16000
	wav := make([]byte, headerLen+len(pcm))
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
	copy(wav[headerLen:], pcm)
	return base64.StdEncoding.EncodeToString(wav)
}
