// Package memory is a stdlib client for the local memory sidecar
// (research/memory/sidecar.py). Memory is best-effort: the sidecar down
// means empty context, never a failed chat.
package memory

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"time"
)

type Client struct {
	base       string
	httpClient *http.Client
}

func NewClient(base string) *Client {
	return &Client{base: base, httpClient: &http.Client{Timeout: 3 * time.Second}}
}

type Fact struct {
	ID   int    `json:"id"`
	Text string `json:"text"`
}

func (c *Client) post(ctx context.Context, path string, payload any, out any) error {
	raw, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.base+path, bytes.NewReader(raw))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	return json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(out)
}

func (c *Client) Remember(ctx context.Context, text string) (Fact, error) {
	var out Fact
	return out, c.post(ctx, "/add", map[string]string{"text": text}, &out)
}

func (c *Client) Forget(ctx context.Context, text string) (bool, error) {
	var out struct {
		Forgot bool `json:"forgot"`
	}
	return out.Forgot, c.post(ctx, "/forget", map[string]string{"text": text}, &out)
}

func (c *Client) Facts(ctx context.Context) ([]Fact, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.base+"/facts", nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out struct {
		Facts []Fact `json:"facts"`
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&out); err != nil {
		return nil, err
	}
	return out.Facts, nil
}

func (c *Client) Context(ctx context.Context, query string) string {
	var out struct {
		Block string `json:"block"`
	}
	if err := c.post(ctx, "/context", map[string]string{"query": query}, &out); err != nil {
		return ""
	}
	return out.Block
}

// Observe feeds one user utterance to automatic capture (rules sync, LLM
// enrichment queued). Callers fire-and-forget it: capture must never slow
// a reply.
func (c *Client) Observe(ctx context.Context, utterance string) ([]Fact, error) {
	var out struct {
		Captured []Fact `json:"captured"`
	}
	if err := c.post(ctx, "/observe", map[string]string{"utterance": utterance}, &out); err != nil {
		return nil, err
	}
	return out.Captured, nil
}
