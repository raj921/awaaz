package handler

// Minimal RFC6455 WebSocket server — stdlib only (the backend gate forbids
// dependencies). ponytail: no fragmentation (FIN-only frames), no
// extensions; gorilla/websocket the upgrade path if a second protocol
// feature (compression, multipart frames) is ever needed.

import (
	"bufio"
	"crypto/sha1"
	"encoding/base64"
	"encoding/binary"
	"errors"
	"io"
	"net"
)

const wsGUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

type wsConn struct {
	conn net.Conn
	br   *bufio.Reader
}

func wsAccept(key string) string {
	h := sha1.Sum([]byte(key + wsGUID))
	return base64.StdEncoding.EncodeToString(h[:])
}

func wsUpgrade(r io.Reader, w io.Writer, key string) error {
	_, err := io.WriteString(w, "HTTP/1.1 101 Switching Protocols\r\n"+
		"Upgrade: websocket\r\nConnection: Upgrade\r\n"+
		"Sec-WebSocket-Accept: "+wsAccept(key)+"\r\n\r\n")
	return err
}

// nextFrame reads one client frame. Only FIN frames with payloads up to
// 1 MiB are supported — our clients never fragment or bulk-transfer.
func (c *wsConn) nextFrame() (opcode byte, payload []byte, err error) {
	var hdr [2]byte
	if _, err = io.ReadFull(c.br, hdr[:]); err != nil {
		return 0, nil, err
	}
	fin, op := hdr[0]&0x80 != 0, hdr[0]&0x0f
	if !fin {
		return 0, nil, errors.New("fragmented frames not supported")
	}
	masked, length := hdr[1]&0x80 != 0, int64(hdr[1]&0x7f)
	switch length {
	case 126:
		var ext [2]byte
		if _, err = io.ReadFull(c.br, ext[:]); err != nil {
			return 0, nil, err
		}
		length = int64(binary.BigEndian.Uint16(ext[:]))
	case 127:
		var ext [8]byte
		if _, err = io.ReadFull(c.br, ext[:]); err != nil {
			return 0, nil, err
		}
		length = int64(binary.BigEndian.Uint64(ext[:]))
	}
	if length > 1<<20 {
		return 0, nil, errors.New("frame too large")
	}
	var key [4]byte
	if masked {
		if _, err = io.ReadFull(c.br, key[:]); err != nil {
			return 0, nil, err
		}
	}
	payload = make([]byte, length)
	if _, err = io.ReadFull(c.br, payload); err != nil {
		return 0, nil, err
	}
	if masked {
		for i := range payload {
			payload[i] ^= key[i%4]
		}
	}
	if op == 8 { // close
		return 8, payload, io.EOF
	}
	if op == 9 { // ping → pong
		_ = c.write(0xA, payload)
		return 9, payload, nil
	}
	return op, payload, nil
}

// write sends one unmasked server frame (server→client frames never mask).
func (c *wsConn) write(opcode byte, payload []byte) error {
	length := len(payload)
	header := []byte{0x80 | opcode}
	switch {
	case length < 126:
		header = append(header, byte(length))
	case length < 65536:
		header = append(header, 126, 0, 0)
		binary.BigEndian.PutUint16(header[2:], uint16(length))
	default:
		header = append(header, 127, 0, 0, 0, 0, 0, 0, 0, 0)
		binary.BigEndian.PutUint64(header[2:], uint64(length))
	}
	// One syscall for small frames; audio frames get the same treatment.
	if _, err := c.conn.Write(append(header, payload...)); err != nil {
		return err
	}
	return nil
}
