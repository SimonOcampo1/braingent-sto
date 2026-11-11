package ui

import (
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"
	"github.com/charmbracelet/x/ansi"

	"github.com/SimonOcampo1/braingent-sto/tui/internal/sto"
)

func loadedModel(t *testing.T) Model {
	t.Helper()
	st := &sto.Status{State: "pending", Up: 3, Phrase: "3 to send", ToBring: 1, Machine: "pc",
		Labels: map[string]string{"act_sync": "Sync", "tui_memories": "Memories", "tui_n_chats": "{n} chats",
			"tui_to_bring": "{n} chats in the cloud you can bring", "k_keep": "keep full chat"}}
	st.Parts.Up = []string{"3 memories"}
	chats := &sto.Chats{Rows: []sto.Chat{
		{ID: "1", Title: "first", Project: "p", Mtime: 2, State: "local"},
		{ID: "2", Title: "second", Project: "p", Mtime: 1, State: "repo"},
	}}
	var m tea.Model = New(sto.Client{}, "/")
	for _, msg := range []tea.Msg{tea.WindowSizeMsg{Width: 120, Height: 30}, loaded{"status", st, nil}, loaded{"chats", chats, nil}} {
		m, _ = m.Update(msg)
	}
	return m.(Model)
}

// click renders m, finds text on screen (on a line that also holds near,
// when given) and clicks its first cell.
func click(t *testing.T, m Model, text string, near ...string) Model {
	t.Helper()
	for y, l := range strings.Split(ansi.Strip(m.View().Content), "\n") {
		if i := strings.Index(l, text); i >= 0 && (len(near) == 0 || strings.Contains(l, near[0])) {
			next, _ := m.Update(tea.MouseClickMsg{X: ansi.StringWidth(l[:i]), Y: y})
			return next.(Model)
		}
	}
	t.Fatalf("%q is not on screen", text)
	return m
}

func TestClicksLandOnWhatTheScreenShows(t *testing.T) {
	m := loadedModel(t)
	if m = click(t, m, "Memories"); m.tab != tMemories {
		t.Fatalf("tab = %d after clicking Memories", m.tab)
	}
	m.tab = tChats
	if m = click(t, m, "second"); m.selected().ID != "2" {
		t.Fatalf("selected %v after clicking its row", m.selected())
	}
	if m = click(t, m, "chats in the cloud"); m.only != "repo" || len(m.lines) != 2 {
		t.Fatalf("only = %q, lines = %d: the card line filters to chats in the cloud", m.only, len(m.lines))
	}
	if m = click(t, m, "Sync "); !m.confirm {
		t.Fatal("clicking Sync opens the summary")
	}
	if m = click(t, m, "Sync", "tui_confirm"); m.confirm || m.busy == "" {
		t.Fatalf("confirm = %v, busy = %q: the popup's button runs the sync", m.confirm, m.busy)
	}
}
