package handler

// Minimal RFC6455 WebSocket server — stdlib only (the backend gate forbids
// dependencies). Supports FIN-only and fragmented data frames, control
// frames (ping/pong/close), and is safe for one reader + concurrent writers.
//
// ponytail: no extensions (permessage-deflate); gorilla/websocket is the
// upgrade path if compression or subprotocol negotiation is ever needed.

import (
	"bufio"
	"crypto/sha1"
	"encoding/base64"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

const wsGUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

// WebSocket opcodes (RFC 6455 §5.2).
const (
	opContinuation byte = 0x0
	opText         byte = 0x1
	opBinary       byte = 0x2
	opClose        byte = 0x8
	opPing         byte = 0x9
	opPong         byte = 0xA
)

// Close codes we send (RFC 6455 §7.4.1).
const (
	closeNormal        uint16 = 1000
	closeProtocolError uint16 = 1002
	closeTooLarge      uint16 = 1009
	closeInternalError uint16 = 1011
)

const (
	// maxFrameBytes caps a single frame. Mic frames are ~8 KiB; the ceiling
	// only exists so a hostile client cannot make us allocate unbounded.
	maxFrameBytes = 1 << 20
	// maxMessageBytes caps a reassembled (fragmented) message. Browsers
	// fragment large sends, so the message cap is what actually protects us.
	maxMessageBytes = 4 << 20
	// maxControlBytes is the RFC limit for control-frame payloads.
	maxControlBytes = 125
)

// errClosed is returned by nextMessage when the peer sent a close frame.
// It is a clean end-of-session, not a failure.
var errClosed = errors.New("websocket: closed by peer")

type wsConn struct {
	conn net.Conn
	br   *bufio.Reader

	// wmu serializes writes: the read loop, the keepalive ticker and the
	// pipeline all emit frames, and interleaved frame headers corrupt the
	// stream. This was previously unguarded.
	wmu sync.Mutex

	writeTimeout time.Duration
	closeOnce    sync.Once
}

func wsAccept(key string) string {
	h := sha1.Sum([]byte(key + wsGUID))
	return base64.StdEncoding.EncodeToString(h[:])
}

// wsHandshakeError describes why an upgrade was refused.
type wsHandshakeError struct{ reason string }

func (e *wsHandshakeError) Error() string { return e.reason }

// checkUpgrade validates the handshake request per RFC 6455 §4.2.1. Header
// values are matched case-insensitively and token-wise: `Connection` is a
// comma-separated list and proxies routinely rewrite the casing of both it
// and `Upgrade`, so the old exact `!= "websocket"` comparison rejected
// perfectly valid clients.
func checkUpgrade(r *http.Request) (key string, err error) {
	if r.Method != http.MethodGet {
		return "", &wsHandshakeError{"websocket upgrade requires GET"}
	}
	if !headerHasToken(r.Header, "Connection", "upgrade") {
		return "", &wsHandshakeError{"missing Connection: Upgrade header"}
	}
	if !strings.EqualFold(strings.TrimSpace(r.Header.Get("Upgrade")), "websocket") {
		return "", &wsHandshakeError{"missing Upgrade: websocket header"}
	}
	if v := strings.TrimSpace(r.Header.Get("Sec-WebSocket-Version")); v != "13" {
		return "", &wsHandshakeError{"unsupported Sec-WebSocket-Version, expected 13"}
	}
	key = strings.TrimSpace(r.Header.Get("Sec-WebSocket-Key"))
	if key == "" {
		return "", &wsHandshakeError{"missing Sec-WebSocket-Key header"}
	}
	// The key must be 16 random bytes, base64-encoded.
	if raw, decErr := base64.StdEncoding.DecodeString(key); decErr != nil || len(raw) != 16 {
		return "", &wsHandshakeError{"malformed Sec-WebSocket-Key"}
	}
	return key, nil
}

// headerHasToken reports whether a comma-separated header contains a token.
func headerHasToken(h http.Header, name, token string) bool {
	for _, value := range h.Values(name) {
		for _, part := range strings.Split(value, ",") {
			if strings.EqualFold(strings.TrimSpace(part), token) {
				return true
			}
		}
	}
	return false
}

// originAllowed guards against cross-site WebSocket hijacking. Browsers do
// not apply CORS to WebSockets, so without this check any site could open a
// room against a user's gateway. A missing Origin (non-browser client) is
// allowed; a present one must be in the allowlist.
func originAllowed(origin string, allowed []string) bool {
	if origin == "" {
		return true
	}
	for _, a := range allowed {
		a = strings.TrimSpace(a)
		if a == "" {
			continue
		}
		if a == "*" || strings.EqualFold(a, origin) {
			return true
		}
	}
	return false
}

// wsUpgrade writes the 101 response completing the handshake.
func wsUpgrade(w io.Writer, key string) error {
	_, err := io.WriteString(w, "HTTP/1.1 101 Switching Protocols\r\n"+
		"Upgrade: websocket\r\nConnection: Upgrade\r\n"+
		"Sec-WebSocket-Accept: "+wsAccept(key)+"\r\n\r\n")
	return err
}

// frame is one raw WebSocket frame off the wire.
type frame struct {
	fin     bool
	opcode  byte
	payload []byte
}

// readFrame reads exactly one frame, unmasking the payload.
func (c *wsConn) readFrame() (frame, error) {
	var hdr [2]byte
	if _, err := io.ReadFull(c.br, hdr[:]); err != nil {
		return frame{}, err
	}
	fin := hdr[0]&0x80 != 0
	// RSV1-3 must be zero: we negotiate no extensions.
	if hdr[0]&0x70 != 0 {
		return frame{}, protocolError("reserved bits set")
	}
	opcode := hdr[0] & 0x0f
	masked := hdr[1]&0x80 != 0
	length := int64(hdr[1] & 0x7f)

	control := opcode&0x08 != 0
	if control {
		// Control frames must not be fragmented and are capped at 125 bytes.
		if !fin {
			return frame{}, protocolError("fragmented control frame")
		}
		if length > maxControlBytes {
			return frame{}, protocolError("oversized control frame")
		}
	}

	switch length {
	case 126:
		var ext [2]byte
		if _, err := io.ReadFull(c.br, ext[:]); err != nil {
			return frame{}, err
		}
		length = int64(binary.BigEndian.Uint16(ext[:]))
	case 127:
		var ext [8]byte
		if _, err := io.ReadFull(c.br, ext[:]); err != nil {
			return frame{}, err
		}
		size := binary.BigEndian.Uint64(ext[:])
		// The high bit must be 0 per RFC, and the value must fit an int64
		// without overflowing into a negative make() argument.
		if size > 1<<62 {
			return frame{}, protocolError("invalid frame length")
		}
		length = int64(size)
	}
	if length > maxFrameBytes {
		return frame{}, &wsCloseError{code: closeTooLarge, reason: "frame too large"}
	}
	// RFC 6455 §5.1: every client→server frame MUST be masked. An unmasked
	// one means a broken or hostile peer.
	if !masked {
		return frame{}, protocolError("unmasked client frame")
	}
	var key [4]byte
	if _, err := io.ReadFull(c.br, key[:]); err != nil {
		return frame{}, err
	}
	payload := make([]byte, length)
	if _, err := io.ReadFull(c.br, payload); err != nil {
		return frame{}, err
	}
	for i := range payload {
		payload[i] ^= key[i%4]
	}
	return frame{fin: fin, opcode: opcode, payload: payload}, nil
}

// nextMessage returns the next complete application message, reassembling
// fragments and answering control frames inline. Browsers fragment large
// sends, so the previous "fragmented frames not supported" hard error broke
// exactly the audio-heavy sessions this server exists to serve.
//
// Returns errClosed after the peer's close frame has been echoed.
func (c *wsConn) nextMessage() (opcode byte, payload []byte, err error) {
	var (
		msgOpcode  byte
		msg        []byte
		assembling bool
	)
	for {
		f, err := c.readFrame()
		if err != nil {
			return 0, nil, err
		}
		switch f.opcode {
		case opClose:
			code, reason := parseClosePayload(f.payload)
			c.writeClose(code, reason)
			return opClose, f.payload, errClosed

		case opPing:
			// Reply with the identical application data (RFC 6455 §5.5.3).
			if err := c.write(opPong, f.payload); err != nil {
				return 0, nil, err
			}

		case opPong:
			// Unsolicited pongs are legal keepalives — ignore.

		case opText, opBinary:
			if assembling {
				return 0, nil, protocolError("new data frame during fragmented message")
			}
			if f.fin {
				if f.opcode == opText && !utf8.Valid(f.payload) {
					return 0, nil, protocolError("invalid UTF-8 in text frame")
				}
				return f.opcode, f.payload, nil
			}
			assembling, msgOpcode, msg = true, f.opcode, f.payload

		case opContinuation:
			if !assembling {
				return 0, nil, protocolError("continuation without initial frame")
			}
			if len(msg)+len(f.payload) > maxMessageBytes {
				return 0, nil, &wsCloseError{code: closeTooLarge, reason: "message too large"}
			}
			msg = append(msg, f.payload...)
			if f.fin {
				if msgOpcode == opText && !utf8.Valid(msg) {
					return 0, nil, protocolError("invalid UTF-8 in text message")
				}
				return msgOpcode, msg, nil
			}

		default:
			return 0, nil, protocolError(fmt.Sprintf("unknown opcode %#x", f.opcode))
		}
	}
}

// write sends one unmasked server frame (server→client frames never mask).
// Safe for concurrent callers.
func (c *wsConn) write(opcode byte, payload []byte) error {
	length := len(payload)
	// Build header + payload in one buffer so a single Write emits a whole
	// frame — a partial write of the header with another goroutine's frame
	// interleaved would desynchronize the stream.
	var header [10]byte
	header[0] = 0x80 | opcode
	var n int
	switch {
	case length < 126:
		header[1] = byte(length)
		n = 2
	case length < 65536:
		header[1] = 126
		binary.BigEndian.PutUint16(header[2:], uint16(length))
		n = 4
	default:
		header[1] = 127
		binary.BigEndian.PutUint64(header[2:], uint64(length))
		n = 10
	}
	buf := make([]byte, 0, n+length)
	buf = append(buf, header[:n]...)
	buf = append(buf, payload...)

	c.wmu.Lock()
	defer c.wmu.Unlock()
	if c.writeTimeout > 0 {
		// Without a write deadline a stalled client (a laptop that slept
		// mid-reply) blocks the session goroutine until the OS gives up.
		_ = c.conn.SetWriteDeadline(time.Now().Add(c.writeTimeout))
		defer c.conn.SetWriteDeadline(time.Time{})
	}
	_, err := c.conn.Write(buf)
	return err
}

// ping sends a keepalive ping. Idle WebSocket connections are killed by
// intermediaries (load balancers, corporate proxies) after 30–60 s, which is
// exactly how a room that "connected fine" goes silent.
func (c *wsConn) ping() error { return c.write(opPing, nil) }

// writeClose sends a close frame once. Further calls are no-ops so the
// deferred close in the handler cannot double-send.
func (c *wsConn) writeClose(code uint16, reason string) {
	c.closeOnce.Do(func() {
		if len(reason) > maxControlBytes-2 {
			reason = reason[:maxControlBytes-2]
		}
		payload := make([]byte, 2, 2+len(reason))
		binary.BigEndian.PutUint16(payload, code)
		payload = append(payload, reason...)
		_ = c.write(opClose, payload)
	})
}

// parseClosePayload extracts the peer's close code, defaulting to normal.
func parseClosePayload(payload []byte) (uint16, string) {
	if len(payload) < 2 {
		return closeNormal, ""
	}
	code := binary.BigEndian.Uint16(payload)
	// Echo back only codes a server is allowed to send.
	if code < 1000 || code == 1005 || code == 1006 || (code > 1013 && code < 3000) {
		code = closeProtocolError
	}
	return code, ""
}

// wsCloseError carries the close code to report to the peer.
type wsCloseError struct {
	code   uint16
	reason string
}

func (e *wsCloseError) Error() string { return "websocket: " + e.reason }

func protocolError(reason string) error {
	return &wsCloseError{code: closeProtocolError, reason: reason}
}

// closeCodeFor maps a read-loop error to the close code we report.
func closeCodeFor(err error) (uint16, string) {
	var ce *wsCloseError
	if errors.As(err, &ce) {
		return ce.code, ce.reason
	}
	if errors.Is(err, errClosed) || errors.Is(err, io.EOF) {
		return closeNormal, ""
	}
	return closeInternalError, "internal error"
}
