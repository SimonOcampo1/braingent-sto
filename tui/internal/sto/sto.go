// Package sto is the TUI's only way into the engine: it runs `sto data` and
// `sto act` and decodes their JSON, the contract the band reads too. No rule
// about chats or the cloud is decided here.
package sto

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"os/exec"
)

// Client runs one `sto` binary; tests point Bin at a fake script.
type Client struct{ Bin string }

// Status is `sto data status`: the one sync state every UI shows.
type Status struct {
	State  string `json:"state"`
	Down   int    `json:"down"`
	Up     int    `json:"up"`
	Phrase string `json:"phrase"`
	Parts  struct {
		Down []string `json:"down"`
		Up   []string `json:"up"`
	} `json:"parts"`
	Chats struct {
		Down int `json:"down"`
		Up   int `json:"up"`
	} `json:"chats"`
	Project    string            `json:"project"`
	ToBring    int               `json:"toBring"`
	FetchError string            `json:"fetchError"`
	Update     int               `json:"update"`
	Machine    string            `json:"machine"`
	Accent     string            `json:"accent"`
	Labels     map[string]string `json:"labels"`
}

// L is the label for key in the configured language, or the key itself.
func (s *Status) L(key string) string {
	if s != nil && s.Labels[key] != "" {
		return s.Labels[key]
	}
	return key
}

// Chat is one row of `sto data chats`. State is "both", "local" or "repo".
type Chat struct {
	ID      string  `json:"id"`
	Title   string  `json:"title"`
	Project string  `json:"project"`
	Machine string  `json:"machine"`
	Mtime   float64 `json:"mtime"`
	State   string  `json:"state"`
}

// Chats is `sto data chats`; Folders maps a project to its folder here, or nil.
type Chats struct {
	Rows    []Chat             `json:"rows"`
	Folders map[string]*string `json:"folders"`
}

// Memories is `sto data memories`, only as far as the header needs it.
type Memories struct {
	Projects []struct {
		Count int `json:"count"`
	} `json:"projects"`
}

// Tools is `sto data tools`, only as far as the header needs it.
type Tools struct {
	Skills  []json.RawMessage `json:"skills"`
	Plugins []json.RawMessage `json:"plugins"`
}

// engineErr is the `{"error": ...}` every sto answer may be instead.
func engineErr(line []byte) error {
	var e struct {
		Error string `json:"error"`
	}
	if json.Unmarshal(line, &e) == nil && e.Error != "" {
		return errors.New(e.Error)
	}
	return nil
}

// Data runs `sto data <view> args...` and decodes the answer into v.
func (c Client) Data(v any, view string, args ...string) error {
	out, err := exec.Command(c.Bin, append([]string{"data", view}, args...)...).Output()
	if err != nil {
		return fmt.Errorf("sto data %s: %w", view, err)
	}
	if err := engineErr(out); err != nil {
		return err
	}
	return json.Unmarshal(out, v)
}

// Act runs `sto act args...`, calling step for each progress line, and
// returns the final line's message or its error.
func (c Client) Act(step func(string), args ...string) (string, error) {
	cmd := exec.Command(c.Bin, append([]string{"act"}, args...)...)
	out, err := cmd.StdoutPipe()
	if err != nil {
		return "", err
	}
	if err := cmd.Start(); err != nil {
		return "", err
	}
	var final struct {
		Step    string `json:"step"`
		Done    bool   `json:"done"`
		Message string `json:"message"`
	}
	var fail error
	sc := bufio.NewScanner(out)
	for sc.Scan() {
		if err := engineErr(sc.Bytes()); err != nil {
			fail = err
			continue
		}
		if json.Unmarshal(sc.Bytes(), &final) == nil && final.Step != "" && !final.Done {
			step(final.Step)
			final.Step = ""
		}
	}
	if err := cmd.Wait(); err != nil && fail == nil {
		fail = fmt.Errorf("sto act: %w", err)
	}
	if fail == nil && !final.Done {
		fail = errors.New("sto act: no final line")
	}
	return final.Message, fail
}
