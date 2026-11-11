// Package sto is the TUI's only way into the engine: it runs `sto data` and
// `sto act` and decodes their JSON, the contract the band reads too. No rule
// about chats or the cloud is decided here.
package sto

import (
	"bufio"
	"context"
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
	FetchError string            `json:"fetchError"`
	Update     int               `json:"update"`
	UpdateLog  []string          `json:"updateLog"`
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

// Memory is one memory of `sto data memories`.
type Memory struct {
	Slug        string  `json:"slug"`
	Type        string  `json:"type"`
	Machine     string  `json:"machine"`
	Mtime       float64 `json:"mtime"`
	Description string  `json:"description"`
}

// MemoryProject is one project's memories.
type MemoryProject struct {
	Project  string   `json:"project"`
	Count    int      `json:"count"`
	Memories []Memory `json:"memories"`
}

// Memories is `sto data memories`, by project.
type Memories struct {
	Projects []MemoryProject `json:"projects"`
}

// Tool is a skill or a plugin; Where is "both", "local", "repo" or "gone".
type Tool struct {
	What  string `json:"what"`
	ID    string `json:"id"`
	Label string `json:"label"`
	Desc  string `json:"desc"`
	Where string `json:"where"`
}

// Tools is `sto data tools`.
type Tools struct {
	Skills  []Tool `json:"skills"`
	Plugins []Tool `json:"plugins"`
}

// Module is one kind of config Sync can carry, and whether it does.
type Module struct {
	ID      string `json:"id"`
	Enabled bool   `json:"enabled"`
}

// Settings is `sto data settings`.
type Settings struct {
	Lang    string   `json:"lang"`
	Langs   []string `json:"langs"`
	Accent  string   `json:"accent"`
	Accents []struct {
		Code string `json:"code"`
		Name string `json:"name"`
	} `json:"accents"`
	Modules []Module `json:"modules"`
	Badge   bool     `json:"badge"`
	Look    struct {
		Icon  string `json:"icon"`
		Color string `json:"color"`
	} `json:"look"`
	Icons  []string `json:"icons"`
	Colors []string `json:"colors"`
	Cloud  string   `json:"cloud"`
}

// Limit is one of the plan's usage windows.
type Limit struct {
	Kind    string `json:"kind"`
	Label   string `json:"label"`
	Percent int    `json:"percent"`
}

// Usage is `sto data usage`.
type Usage struct {
	Limits []Limit `json:"limits"`
}

// Hit is one result of `sto data search`; Ref says where it lives, by kind.
type Hit struct {
	Kind  string         `json:"kind"`
	Label string         `json:"label"`
	Sub   string         `json:"sub"`
	Ref   map[string]any `json:"ref"`
}

// Search is `sto data search --q`.
type Search struct {
	Hits []Hit `json:"hits"`
}

// Turn is one turn of a chat: Who is "user" or "claude".
type Turn struct {
	Who      string `json:"who"`
	Markdown string `json:"markdown"`
}

// Detail is `sto data detail <kind> <id>`: what the reader shows. A chat
// comes in Turns too, so the reader can tell who spoke.
type Detail struct {
	Title    string `json:"title"`
	Markdown string `json:"markdown"`
	Turns    []Turn `json:"turns"`
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
	return c.DataCtx(context.Background(), v, view, args...)
}

// DataCtx is Data that dies with ctx: a search the next key made stale.
func (c Client) DataCtx(ctx context.Context, v any, view string, args ...string) error {
	out, err := exec.CommandContext(ctx, c.Bin, append([]string{"data", view}, args...)...).Output()
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
