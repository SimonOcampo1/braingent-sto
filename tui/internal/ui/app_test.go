package ui

import (
	"fmt"
	"os"
	"path/filepath"
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
	if m = click(t, m, "second"); m.selected().id != "2" {
		t.Fatalf("selected %v after clicking its row", m.selected())
	}
	if m = click(t, m, "chats in the cloud"); m.only != "repo" || len(m.lists[tChats].lines) != 2 {
		t.Fatalf("only = %q, lines = %d: the card line filters to chats in the cloud", m.only, len(m.lists[tChats].lines))
	}
	if m = click(t, m, "Sync "); !m.confirm {
		t.Fatal("clicking Sync opens the summary")
	}
	if m = click(t, m, "Sync", "tui_confirm"); m.confirm || m.busy == "" {
		t.Fatalf("confirm = %v, busy = %q: the popup's button runs the sync", m.confirm, m.busy)
	}
}

func press(m Model, keys ...string) (Model, tea.Cmd) {
	var cmd tea.Cmd
	for _, k := range keys {
		var next tea.Model
		r := []rune(k)
		key := tea.KeyPressMsg{Text: k}
		switch k {
		case "enter":
			key = tea.KeyPressMsg{Code: tea.KeyEnter}
		case "esc":
			key = tea.KeyPressMsg{Code: tea.KeyEscape}
		default:
			key.Code = r[0]
		}
		next, cmd = m.Update(key)
		m = next.(Model)
	}
	return m, cmd
}

func TestSearchJumpsToTheHitInItsTab(t *testing.T) {
	m := loadedModel(t)
	m.items[tMemories] = []item{{kind: "memory", id: "p/pc/s", title: "s", group: "p"}, {kind: "memory", id: "p/pc/z", title: "z", group: "p"}}
	m.rebuild(tMemories)
	m, cmd := press(m, "/", "z", "e", "enter")
	if m.query != "ze" || cmd == nil || !m.searching || m.typing {
		t.Fatalf("query = %q, searching = %v, typing = %v", m.query, m.searching, m.typing)
	}
	next, _ := m.Update(loaded{"search", &sto.Search{Hits: []sto.Hit{
		{Kind: "memory", Label: "z", Ref: map[string]any{"project": "p", "machine": "pc", "slug": "z"}}}}, nil})
	m, _ = press(next.(Model), "enter")
	if m.searching || m.tab != tMemories || m.selected().id != "p/pc/z" {
		t.Fatalf("tab = %d, searching = %v, selected = %+v", m.tab, m.searching, m.selected())
	}
}

func TestEnterReadsAChatAndEscGoesBack(t *testing.T) {
	m, cmd := press(loadedModel(t), "enter")
	if m.read == nil || cmd == nil {
		t.Fatal("enter on a chat opens the reader and loads it")
	}
	next, _ := m.Update(loaded{"detail", &sto.Detail{Title: "first", Markdown: "# Hello reader"}, nil})
	m = next.(Model)
	if !strings.Contains(ansi.Strip(m.View().Content), "Hello reader") {
		t.Fatal("the reader shows the markdown")
	}
	if m, _ = press(m, "esc"); m.read != nil {
		t.Fatal("esc closes the reader")
	}
}

func TestChangingASettingAsksForTheNextChoice(t *testing.T) {
	dir := t.TempDir()
	bin, log := filepath.Join(dir, "sto"), filepath.Join(dir, "args")
	os.WriteFile(bin, []byte("#!/bin/sh\necho \"$@\" > "+log+"\necho '{\"done\": true, \"message\": \"\"}'\n"), 0o755)
	m := loadedModel(t)
	m.c = sto.Client{Bin: bin}
	set := &sto.Settings{Lang: "es", Langs: []string{"en", "es"}}
	next, _ := m.Update(loaded{"settings", set, nil})
	m = next.(Model)
	m.tab = tSettings
	m, cmd := press(m, "enter") // the first setting is the language
	if cmd == nil {
		t.Fatal("enter on a setting changes it")
	}
	if msg := cmd().(tea.BatchMsg)[0](); msg.(actDone).err != nil { // [1] is the spinner
		t.Fatal(msg.(actDone).err)
	}
	if got, _ := os.ReadFile(log); strings.TrimSpace(string(got)) != "act set lang en" {
		t.Fatalf("sto got %q", got)
	}
}

func TestTheReaderTellsYourTurnsFromClaudes(t *testing.T) {
	m, _ := press(loadedModel(t), "enter")
	m.st.Labels["tui_you"], m.st.Labels["tui_claude"] = "you", "Claude"
	next, _ := m.Update(loaded{"detail", &sto.Detail{Title: "first", Turns: []sto.Turn{
		{Who: "user", Markdown: "why is it slow"}, {Who: "claude", Markdown: "because of the index"}}}, nil})
	var mine, theirs string
	for _, l := range strings.Split(ansi.Strip(next.(Model).View().Content), "\n") {
		if strings.Contains(l, "why is it slow") {
			mine = l
		}
		if strings.Contains(l, "because of the index") {
			theirs = l
		}
	}
	// each turn carries its own bar down its left edge, and they differ
	if !strings.Contains(mine, "▌") || strings.Contains(theirs, "▌") || !strings.Contains(theirs, "│") {
		t.Fatalf("mine = %q\ntheirs = %q", mine, theirs)
	}
}

func TestGroupsFoldOneByOneOrAllAtOnce(t *testing.T) {
	m := loadedModel(t)
	m.items[tChats] = append(m.items[tChats], item{kind: "chat", id: "3", title: "third", group: "q", mtime: 0.5})
	m.rebuild(tChats)
	if m, _ = press(m, "c"); len(m.lists[tChats].lines) != 2 { // title p, title q
		t.Fatalf("c folds every group: %v", describe(m.lists[tChats].lines))
	}
	m, _ = press(m, "space") // the cursor is on the first title
	if got := fmt.Sprint(describe(m.lists[tChats].lines)); got != "[title p 2 false first second spacer title q 1 false folded]" {
		t.Fatalf("space opens the group under the cursor: %v", got)
	}
	if m, _ = press(m, "c"); len(m.lists[tChats].lines) != 2 {
		t.Fatal("c folds them all again while one is open")
	}
	if m, _ = press(m, "c"); len(m.lists[tChats].lines) != 6 {
		t.Fatalf("c opens them all when every one is folded: %v", describe(m.lists[tChats].lines))
	}
}

func TestTheSpinnerTurnsWhileAnActRuns(t *testing.T) {
	m := loadedModel(t)
	m.busy = "bringing chats"
	before := m.footer(80)
	next, cmd := m.Update(tickMsg{})
	if after := next.(Model).footer(80); after == before || cmd == nil || !strings.Contains(ansi.Strip(after), "bringing chats") {
		t.Fatalf("before %q, after %q, cmd %v", before, after, cmd)
	}
	m.busy = ""
	if _, cmd := m.Update(tickMsg{}); cmd != nil {
		t.Fatal("the spinner stops when the act ends")
	}
}

func TestHomeAndEndJumpToTheEnds(t *testing.T) {
	m := loadedModel(t)
	end := tea.KeyPressMsg{Code: tea.KeyEnd}
	next, _ := m.Update(end)
	if m = next.(Model); m.selected() == nil || m.selected().id != "2" {
		t.Fatalf("end selects the last row, got %+v", m.selected())
	}
	next, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyHome})
	if m = next.(Model); m.cur().cur != 0 {
		t.Fatalf("home goes to the first line, got %d", m.cur().cur)
	}
}

func TestTheGroupCountSitsAtTheRightEdge(t *testing.T) {
	m := loadedModel(t)
	r := ansi.Strip(m.titleRow(line{group: "proj", count: 12}, 60, false))
	if ansi.StringWidth(r) != 60 || !strings.HasSuffix(strings.TrimRight(r, " "), "12 chats") {
		t.Fatalf("%q (width %d)", r, ansi.StringWidth(r))
	}
}

func TestTheSearchFilterKeepsOneKind(t *testing.T) {
	m := loadedModel(t)
	m.searching = true
	next, _ := m.Update(loaded{"search", &sto.Search{Hits: []sto.Hit{
		{Kind: "session", Label: "a chat", Ref: map[string]any{"id": "c", "project": "p"}},
		{Kind: "memory", Label: "a memory", Ref: map[string]any{"project": "p", "machine": "m", "slug": "s"}}}}, nil})
	m, _ = press(next.(Model), "f") // all -> chats
	var titles []string
	for _, l := range m.lists[tSearch].lines {
		if l.it != nil {
			titles = append(titles, l.it.title)
		}
	}
	if fmt.Sprint(titles) != "[a chat]" {
		t.Fatalf("f keeps the chats only: %v", titles)
	}
}

func TestActionOnAGroupTitleBringsItsCloudChats(t *testing.T) {
	dir := t.TempDir()
	bin, log := filepath.Join(dir, "sto"), filepath.Join(dir, "args")
	os.WriteFile(bin, []byte("#!/bin/sh\necho \"$@\" > "+log+"\necho '{\"done\": true, \"message\": \"\"}'\n"), 0o755)
	m := loadedModel(t)
	m.c = sto.Client{Bin: bin}
	m, _ = press(m, "home") // the title of p, which holds one chat only in the cloud
	if m.selected() != nil {
		t.Fatal("home lands on the group title")
	}
	m, cmd := press(m, "a")
	if cmd == nil {
		t.Fatal("a on a title brings the group's cloud chats")
	}
	cmd().(tea.BatchMsg)[0]()
	if got, _ := os.ReadFile(log); strings.TrimSpace(string(got)) != "act bring-chats p" {
		t.Fatalf("sto got %q", got)
	}
}
