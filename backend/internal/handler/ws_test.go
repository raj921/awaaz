package handler

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"io"
	"math"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"awaaz/internal/modal"
)

// --- client-side helpers: a tiny masked WebSocket client for the tests. ---

type testClient struct {
	conn net.Conn
	buf  []byte
}

// dialRoom opens a real WebSocket room against a real server and completes
// the handshake, returning a client that speaks masked frames.
func dialRoom(t *testing.T, srv *httptest.Server, query, origin string) *testClient {
	t.Helper()
	conn, err := net.Dial("tcp", strings.TrimPrefix(srv.URL, "http://"))
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	t.Cleanup(func() { conn.Close() })

	var keyRaw [16]byte
	if _, err := rand.Read(keyRaw[:]); err != nil {
		t.Fatalf("rand: %v", err)
	}
	key := base64.StdEncoding.EncodeToString(keyRaw[:])

	req := "GET /api/v1/voice/session" + query + " HTTP/1.1\r\n" +
		"Host: " + strings.TrimPrefix(srv.URL, "http://") + "\r\n" +
		"Upgrade: WebSocket\r\n" + // deliberately odd casing: must still work
		"Connection: keep-alive, Upgrade\r\n" + // token list: must still work
		"Sec-WebSocket-Version: 13\r\n" +
		"Sec-WebSocket-Key: " + key + "\r\n"
	if origin != "" {
		req += "Origin: " + origin + "\r\n"
	}
	req += "\r\n"
	if _, err := io.WriteString(conn, req); err != nil {
		t.Fatalf("write handshake: %v", err)
	}

	c := &testClient{conn: conn}
	status := c.readLine(t)
	if !strings.Contains(status, "101") {
		// Drain so the failure message shows the real reason.
		rest := make([]byte, 512)
		n, _ := conn.Read(rest)
		t.Fatalf("handshake failed: %q %s", status, rest[:n])
	}
	for {
		line := c.readLine(t)
		if line == "" {
			break
		}
		if strings.HasPrefix(strings.ToLower(line), "sec-websocket-accept:") {
			want := wsAccept(key)
			if got := strings.TrimSpace(strings.SplitN(line, ":", 2)[1]); got != want {
				t.Fatalf("bad accept: got %q want %q", got, want)
			}
		}
	}
	return c
}

// dialExpectRefused performs the handshake expecting a non-101 response.
func dialExpectRefused(t *testing.T, srv *httptest.Server, origin string) string {
	t.Helper()
	conn, err := net.Dial("tcp", strings.TrimPrefix(srv.URL, "http://"))
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer conn.Close()
	var keyRaw [16]byte
	_, _ = rand.Read(keyRaw[:])
	req := "GET /api/v1/voice/session HTTP/1.1\r\nHost: x\r\n" +
		"Upgrade: websocket\r\nConnection: Upgrade\r\n" +
		"Sec-WebSocket-Version: 13\r\n" +
		"Sec-WebSocket-Key: " + base64.StdEncoding.EncodeToString(keyRaw[:]) + "\r\n" +
		"Origin: " + origin + "\r\n\r\n"
	_, _ = io.WriteString(conn, req)
	_ = conn.SetReadDeadline(time.Now().Add(3 * time.Second))
	out := make([]byte, 256)
	n, _ := conn.Read(out)
	return string(out[:n])
}

func (c *testClient) readLine(t *testing.T) string {
	t.Helper()
	var line []byte
	one := make([]byte, 1)
	_ = c.conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	for {
		if _, err := io.ReadFull(c.conn, one); err != nil {
			t.Fatalf("read header line: %v", err)
		}
		if one[0] == '\n' {
			return strings.TrimSuffix(string(line), "\r")
		}
		line = append(line, one[0])
	}
}

// send writes one masked client frame.
func (c *testClient) send(t *testing.T, opcode byte, payload []byte) {
	t.Helper()
	var mask [4]byte
	_, _ = rand.Read(mask[:])
	header := []byte{0x80 | opcode}
	n := len(payload)
	switch {
	case n < 126:
		header = append(header, 0x80|byte(n))
	case n < 65536:
		header = append(header, 0x80|126, 0, 0)
		binary.BigEndian.PutUint16(header[2:], uint16(n))
	default:
		header = append(header, 0x80|127, 0, 0, 0, 0, 0, 0, 0, 0)
		binary.BigEndian.PutUint64(header[2:], uint64(n))
	}
	header = append(header, mask[:]...)
	masked := make([]byte, n)
	for i := range payload {
		masked[i] = payload[i] ^ mask[i%4]
	}
	_ = c.conn.SetWriteDeadline(time.Now().Add(5 * time.Second))
	if _, err := c.conn.Write(append(header, masked...)); err != nil {
		t.Fatalf("send frame: %v", err)
	}
}

// sendFragmented writes a message split across two frames plus a
// continuation, which is what browsers do for large sends.
func (c *testClient) sendFragmented(t *testing.T, opcode byte, a, b []byte) {
	t.Helper()
	c.sendRaw(t, false, opcode, a)
	c.sendRaw(t, true, opContinuation, b)
}

func (c *testClient) sendRaw(t *testing.T, fin bool, opcode byte, payload []byte) {
	t.Helper()
	var mask [4]byte
	_, _ = rand.Read(mask[:])
	first := opcode
	if fin {
		first |= 0x80
	}
	header := []byte{first}
	n := len(payload)
	switch {
	case n < 126:
		header = append(header, 0x80|byte(n))
	default:
		header = append(header, 0x80|126, 0, 0)
		binary.BigEndian.PutUint16(header[2:], uint16(n))
	}
	header = append(header, mask[:]...)
	masked := make([]byte, n)
	for i := range payload {
		masked[i] = payload[i] ^ mask[i%4]
	}
	_ = c.conn.SetWriteDeadline(time.Now().Add(5 * time.Second))
	if _, err := c.conn.Write(append(header, masked...)); err != nil {
		t.Fatalf("send fragment: %v", err)
	}
}

// recv reads one server frame (server frames are never masked).
func (c *testClient) recv(t *testing.T, timeout time.Duration) (byte, []byte) {
	t.Helper()
	_ = c.conn.SetReadDeadline(time.Now().Add(timeout))
	var hdr [2]byte
	if _, err := io.ReadFull(c.conn, hdr[:]); err != nil {
		t.Fatalf("read frame header: %v", err)
	}
	opcode := hdr[0] & 0x0f
	if hdr[1]&0x80 != 0 {
		t.Fatal("server frame must not be masked")
	}
	length := int64(hdr[1] & 0x7f)
	switch length {
	case 126:
		var ext [2]byte
		if _, err := io.ReadFull(c.conn, ext[:]); err != nil {
			t.Fatalf("read ext16: %v", err)
		}
		length = int64(binary.BigEndian.Uint16(ext[:]))
	case 127:
		var ext [8]byte
		if _, err := io.ReadFull(c.conn, ext[:]); err != nil {
			t.Fatalf("read ext64: %v", err)
		}
		length = int64(binary.BigEndian.Uint64(ext[:]))
	}
	payload := make([]byte, length)
	if _, err := io.ReadFull(c.conn, payload); err != nil {
		t.Fatalf("read payload: %v", err)
	}
	return opcode, payload
}

// recvJSON reads frames until a JSON message of the given type arrives.
func (c *testClient) recvJSON(t *testing.T, wantType string, timeout time.Duration) map[string]any {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		op, payload := c.recv(t, time.Until(deadline))
		if op != opText {
			continue
		}
		var msg map[string]any
		if err := json.Unmarshal(payload, &msg); err != nil {
			t.Fatalf("bad json %q: %v", payload, err)
		}
		if msg["type"] == wantType {
			return msg
		}
	}
	t.Fatalf("timed out waiting for %q message", wantType)
	return nil
}

// loudPCM builds n bytes of PCM16 well above the VAD speech threshold.
func loudPCM(n int) []byte {
	pcm := make([]byte, n)
	for i := 0; i+1 < n; i += 2 {
		v := int16(8000 * math.Sin(float64(i)*0.05))
		binary.LittleEndian.PutUint16(pcm[i:], uint16(v))
	}
	return pcm
}

func newRoomServer(t *testing.T, gw *fakeGateway) *httptest.Server {
	t.Helper()
	h := New(gw)
	h.AllowOrigins("http://localhost:3000")
	srv := httptest.NewServer(NewMux(h))
	t.Cleanup(srv.Close)
	return srv
}

// --- the tests ---

// TestWSHandshakeAcceptsRealBrowserHeaders is the regression test for the
// reported bug: the socket connected but the session never listened. Real
// browsers/proxies send "Connection: keep-alive, Upgrade" and vary casing,
// which the old exact-match check rejected.
func TestWSHandshakeAcceptsRealBrowserHeaders(t *testing.T) {
	srv := newRoomServer(t, &fakeGateway{})
	c := dialRoom(t, srv, "", "http://localhost:3000")

	room := c.recvJSON(t, "room", 5*time.Second)
	if id, _ := room["id"].(string); !strings.HasPrefix(id, "r-") {
		t.Fatalf("bad room id %q", id)
	}
	state := c.recvJSON(t, "state", 5*time.Second)
	if state["value"] != "listening" {
		t.Fatalf("room did not start listening: %v", state)
	}
}

// TestWSRejectsForeignOrigin proves cross-site hijacking is blocked.
func TestWSRejectsForeignOrigin(t *testing.T) {
	srv := newRoomServer(t, &fakeGateway{})
	resp := dialExpectRefused(t, srv, "http://evil.example")
	if !strings.Contains(resp, "403") {
		t.Fatalf("foreign origin was not refused: %q", resp)
	}
}

// TestWSRejectsBadVersion covers handshake validation.
func TestWSRejectsBadVersion(t *testing.T) {
	srv := newRoomServer(t, &fakeGateway{})
	conn, err := net.Dial("tcp", strings.TrimPrefix(srv.URL, "http://"))
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer conn.Close()
	_, _ = io.WriteString(conn, "GET /api/v1/voice/session HTTP/1.1\r\nHost: x\r\n"+
		"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 8\r\n"+
		"Sec-WebSocket-Key: AAAAAAAAAAAAAAAAAAAAAA==\r\n\r\n")
	_ = conn.SetReadDeadline(time.Now().Add(3 * time.Second))
	out := make([]byte, 256)
	n, _ := conn.Read(out)
	if !strings.Contains(string(out[:n]), "400") {
		t.Fatalf("bad version accepted: %q", out[:n])
	}
}

// TestWSPingIsAnsweredWithPong proves the keepalive path works — without it
// proxies silently drop the idle room mid-session.
func TestWSPingIsAnsweredWithPong(t *testing.T) {
	srv := newRoomServer(t, &fakeGateway{})
	c := dialRoom(t, srv, "", "http://localhost:3000")
	c.recvJSON(t, "room", 5*time.Second)
	c.recvJSON(t, "state", 5*time.Second)

	c.send(t, opPing, []byte("hb"))
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		op, payload := c.recv(t, time.Until(deadline))
		if op == opPong {
			if string(payload) != "hb" {
				t.Fatalf("pong payload not echoed: %q", payload)
			}
			return
		}
	}
	t.Fatal("no pong received")
}

// TestWSPushToTalkTurn is the full listening session: hold, stream audio,
// release, and get a reply back. This is the behaviour the user reported as
// broken ("pressing the button does not listen").
func TestWSPushToTalkTurn(t *testing.T) {
	gw := &fakeGateway{asrOut: "नमस्ते", chatReply: modal.ChatResult{Reply: "हाँ जी बोलिए"}}
	srv := newRoomServer(t, gw)
	c := dialRoom(t, srv, "?provider=awaaz", "http://localhost:3000")
	c.recvJSON(t, "room", 5*time.Second)
	c.recvJSON(t, "state", 5*time.Second)

	c.send(t, opText, []byte(`{"type":"hold","active":true}`))
	// Stream ~0.5 s of speech in browser-sized chunks.
	chunk := loudPCM(4096)
	for range 4 {
		c.send(t, opBinary, chunk)
	}
	// A hold must survive a pause longer than the VAD silence window.
	time.Sleep(vadSilence + 200*time.Millisecond)
	c.send(t, opBinary, chunk)
	c.send(t, opText, []byte(`{"type":"flush"}`))

	if got := c.recvJSON(t, "state", 5*time.Second); got["value"] != "thinking" {
		t.Fatalf("release did not start a turn: %v", got)
	}
	reply := c.recvJSON(t, "reply", 10*time.Second)
	if reply["heard"] != "नमस्ते" || reply["reply"] != "हाँ जी बोलिए" {
		t.Fatalf("unexpected turn result: %v", reply)
	}
}

// TestWSFragmentedAudioIsReassembled covers the frames browsers actually
// send for large buffers; the old server hard-errored on them.
func TestWSFragmentedAudioIsReassembled(t *testing.T) {
	gw := &fakeGateway{asrOut: "हाय", chatReply: modal.ChatResult{Reply: "जी"}}
	srv := newRoomServer(t, gw)
	c := dialRoom(t, srv, "", "http://localhost:3000")
	c.recvJSON(t, "room", 5*time.Second)
	c.recvJSON(t, "state", 5*time.Second)

	c.send(t, opText, []byte(`{"type":"hold","active":true}`))
	half := loudPCM(6000)
	c.sendFragmented(t, opBinary, half, half)
	c.send(t, opText, []byte(`{"type":"flush"}`))

	if got := c.recvJSON(t, "state", 5*time.Second); got["value"] != "thinking" {
		t.Fatalf("fragmented audio was not accepted: %v", got)
	}
	c.recvJSON(t, "reply", 10*time.Second)
}

// TestWSSilentTurnIsDropped proves an idle mic never triggers a phantom turn.
func TestWSSilentTurnIsDropped(t *testing.T) {
	srv := newRoomServer(t, &fakeGateway{})
	c := dialRoom(t, srv, "", "http://localhost:3000")
	c.recvJSON(t, "room", 5*time.Second)
	c.recvJSON(t, "state", 5*time.Second)

	c.send(t, opBinary, make([]byte, 16000)) // pure silence
	c.send(t, opText, []byte(`{"type":"flush"}`))
	// The room must stay listening: no "thinking" state, no reply.
	c.send(t, opText, []byte(`{"type":"stop"}`))
	got := c.recvJSON(t, "state", 5*time.Second)
	if got["value"] != "ended" {
		t.Fatalf("silence produced an unexpected turn: %v", got)
	}
}

// TestWSStopClosesCleanly covers the disconnect path.
func TestWSStopClosesCleanly(t *testing.T) {
	srv := newRoomServer(t, &fakeGateway{})
	c := dialRoom(t, srv, "", "http://localhost:3000")
	c.recvJSON(t, "room", 5*time.Second)
	c.recvJSON(t, "state", 5*time.Second)

	c.send(t, opText, []byte(`{"type":"stop"}`))
	if got := c.recvJSON(t, "state", 5*time.Second); got["value"] != "ended" {
		t.Fatalf("stop not acknowledged: %v", got)
	}
	op, _ := c.recv(t, 5*time.Second)
	if op != opClose {
		t.Fatalf("expected close frame, got opcode %#x", op)
	}
}

// TestWSUnmaskedClientFrameRejected covers RFC 6455 §5.1 enforcement.
func TestWSUnmaskedClientFrameRejected(t *testing.T) {
	srv := newRoomServer(t, &fakeGateway{})
	c := dialRoom(t, srv, "", "http://localhost:3000")
	c.recvJSON(t, "room", 5*time.Second)
	c.recvJSON(t, "state", 5*time.Second)

	// Unmasked text frame — illegal from a client.
	_, _ = c.conn.Write([]byte{0x81, 0x02, 'h', 'i'})
	op, payload := c.recv(t, 5*time.Second)
	if op != opClose {
		t.Fatalf("expected close, got opcode %#x", op)
	}
	if code := binary.BigEndian.Uint16(payload); code != closeProtocolError {
		t.Fatalf("expected protocol error close code, got %d", code)
	}
}

func TestWSAcceptKeyMatchesRFCExample(t *testing.T) {
	// RFC 6455 §1.3 worked example.
	if got := wsAccept("dGhlIHNhbXBsZSBub25jZQ=="); got != "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=" {
		t.Fatalf("wsAccept = %q", got)
	}
}

func TestOriginAllowed(t *testing.T) {
	allow := []string{"http://localhost:3000", "https://awaaz.app"}
	cases := []struct {
		origin string
		want   bool
	}{
		{"", true}, // non-browser client
		{"http://localhost:3000", true},
		{"https://awaaz.app", true},
		{"http://evil.example", false},
		{"http://localhost:3001", false},
	}
	for _, tc := range cases {
		if got := originAllowed(tc.origin, allow); got != tc.want {
			t.Errorf("originAllowed(%q) = %v, want %v", tc.origin, got, tc.want)
		}
	}
	if !originAllowed("http://anything", []string{"*"}) {
		t.Error("wildcard should allow any origin")
	}
}

// TestHeaderHasToken covers the comma-separated Connection header parsing
// that browsers and proxies actually produce.
func TestHeaderHasToken(t *testing.T) {
	h := http.Header{}
	h.Set("Connection", "keep-alive, Upgrade")
	if !headerHasToken(h, "Connection", "upgrade") {
		t.Error("token list not parsed")
	}
	h.Set("Connection", "close")
	if headerHasToken(h, "Connection", "upgrade") {
		t.Error("false positive")
	}
}
