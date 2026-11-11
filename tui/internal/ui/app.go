// Package ui is the braingent TUI: a header with the tabs and the sync
// state, a card with the one Sync button, and each tab's list beside a
// sidebar that explains the selected item. Every number and word comes from
// `sto data`; this package only lays them out.
package ui

import (
	"fmt"
	"strings"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"

	"github.com/SimonOcampo1/braingent-sto/tui/internal/sto"
)

const (
	tChats = iota
	tMemories
	tTools
	tSettings
)

var tabKeys = [4]string{"tui_chats", "tui_memories", "tui_tools", "tui_settings"}

type loaded struct {
	view string
	v    any
	err  error
}

type stepMsg string

type actDone struct {
	msg string
	err error
}

// frame is what View learns about the screen and Update needs back: where
// each clickable thing is, and how far the list is scrolled. View has a
// value receiver, so it lives behind a pointer.
type frame struct {
	hits hits
	top  int
}

// Model is the whole TUI state.
type Model struct {
	c   sto.Client
	cwd string

	w, h   int
	tab    int
	st     *sto.Status
	chats  *sto.Chats
	counts [4]int // -1 until loaded; Settings has none
	errs   []string

	grouped bool
	only    string // "repo" after the card's "chats you can bring" line; esc clears it
	lines   []line
	cur     int

	confirm bool   // the Sync summary is open
	busy    string // progress of a running act; keys wait while it is set
	flash   string
	failed  bool
	ch      chan tea.Msg
	fr      *frame
}

// New is a TUI reading c, run from the folder cwd.
func New(c sto.Client, cwd string) Model {
	return Model{c: c, cwd: cwd, counts: [4]int{-1, -1, -1, -1}, grouped: true, fr: &frame{}}
}

func (m Model) L(key string) string { return m.st.L(key) }

func (m Model) load(view string) tea.Cmd {
	c, cwd := m.c, m.cwd
	return func() tea.Msg {
		var v any
		var err error
		switch view {
		case "status":
			s := &sto.Status{}
			err, v = c.Data(s, "status", "--all", "--cwd", cwd), s
		case "chats":
			s := &sto.Chats{}
			err, v = c.Data(s, "chats"), s
		case "memories":
			s := &sto.Memories{}
			err, v = c.Data(s, "memories"), s
		case "tools":
			s := &sto.Tools{}
			err, v = c.Data(s, "tools"), s
		}
		return loaded{view, v, err}
	}
}

func (m Model) Init() tea.Cmd {
	return tea.Batch(m.load("status"), m.load("chats"), m.load("memories"), m.load("tools"))
}

func listen(ch chan tea.Msg) tea.Cmd { return func() tea.Msg { return <-ch } }

// act runs `sto act args...`, its progress arriving as stepMsg and its end
// as actDone.
func (m *Model) act(args ...string) tea.Cmd {
	c, ch := m.c, make(chan tea.Msg, 16)
	m.ch, m.busy, m.flash = ch, m.L("mod_syncing"), ""
	go func() {
		msg, err := c.Act(func(s string) { ch <- stepMsg(s) }, args...)
		ch <- actDone{msg, err}
	}()
	return listen(ch)
}

// rebuild lays the chats out again, keeping the cursor on the same chat.
func (m *Model) rebuild() {
	if m.chats == nil {
		return
	}
	id := ""
	if c := m.selected(); c != nil {
		id = c.ID
	}
	rows := m.chats.Rows
	if m.only != "" {
		rows = nil
		for _, r := range m.chats.Rows {
			if r.State == m.only {
				rows = append(rows, r)
			}
		}
	}
	here := ""
	if m.st != nil {
		here = m.st.Project
	}
	m.lines, m.cur = arrange(rows, here, m.grouped), -1
	for i, l := range m.lines {
		if l.chat != nil && l.chat.ID == id {
			m.cur = i
		}
	}
	if m.cur < 0 {
		m.cur = step(m.lines, -1, 1)
	}
}

func (m *Model) selected() *sto.Chat {
	if m.cur >= 0 && m.cur < len(m.lines) {
		return m.lines[m.cur].chat
	}
	return nil
}

// itemAct is the one thing the selected chat can do from here: keep a chat
// only on this machine, bring one only in the cloud.
func (m *Model) itemAct() tea.Cmd {
	c := m.selected()
	if c == nil {
		return nil
	}
	switch c.State {
	case "local":
		return m.act("keep", c.ID)
	case "repo":
		return m.act("resume", c.ID)
	}
	return nil
}

func (m *Model) openSync() {
	if m.st != nil && m.st.State == "pending" {
		m.confirm = true
	}
}

func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.w, m.h = msg.Width, msg.Height
	case loaded:
		if msg.err != nil {
			m.errs = append(m.errs, msg.view+": "+msg.err.Error())
			break
		}
		switch v := msg.v.(type) {
		case *sto.Status:
			m.st = v
			setAccent(v.Accent)
		case *sto.Chats:
			m.chats, m.counts[tChats] = v, len(v.Rows)
		case *sto.Memories:
			n := 0
			for _, p := range v.Projects {
				n += p.Count
			}
			m.counts[tMemories] = n
		case *sto.Tools:
			m.counts[tTools] = len(v.Skills) + len(v.Plugins)
		}
		m.rebuild()
	case stepMsg:
		m.busy = string(msg)
		return m, listen(m.ch)
	case actDone:
		m.busy, m.flash, m.failed = "", msg.msg, msg.err != nil
		if msg.err != nil {
			m.flash = msg.err.Error()
		}
		return m, tea.Batch(m.load("status"), m.load("chats"))
	case tea.KeyPressMsg:
		if msg.String() == "ctrl+c" {
			return m, tea.Quit
		}
		if m.busy != "" {
			break
		}
		m.flash = ""
		if m.confirm {
			m.confirm = false
			if msg.String() == "enter" {
				return m, m.act("sync", "--all")
			}
			break
		}
		switch msg.String() {
		case "q":
			return m, tea.Quit
		case "tab":
			m.tab = (m.tab + 1) % len(tabKeys)
		case "shift+tab":
			m.tab = (m.tab + len(tabKeys) - 1) % len(tabKeys)
		case "j", "down":
			m.cur = step(m.lines, m.cur, 1)
		case "k", "up":
			m.cur = step(m.lines, m.cur, -1)
		case "b":
			m.grouped = !m.grouped
			m.rebuild()
		case "a":
			return m, m.itemAct()
		case "S":
			m.openSync()
		case "esc":
			m.only = ""
			m.rebuild()
		}
	case tea.MouseWheelMsg:
		if msg.Button == tea.MouseWheelUp {
			m.cur = step(m.lines, m.cur, -1)
		} else {
			m.cur = step(m.lines, m.cur, 1)
		}
	case tea.MouseClickMsg:
		if m.busy != "" {
			break
		}
		t, ok := m.fr.hits.at(msg.X, msg.Y)
		if m.confirm {
			m.confirm = false
			if ok && t.kind == "confirm" {
				return m, m.act("sync", "--all")
			}
			break
		}
		switch t.kind {
		case "tab":
			m.tab = t.i
		case "row":
			m.tab, m.cur = tChats, t.i
		case "sync":
			m.openSync()
		case "bring":
			m.tab, m.only = tChats, "repo"
			m.rebuild()
		case "item":
			return m, m.itemAct()
		}
	}
	return m, nil
}

// ---------- view ----------

func ago(ts float64) string {
	t := time.Unix(int64(ts), 0)
	d := time.Since(t)
	switch {
	case d < time.Hour:
		return fmt.Sprintf("%dm", int(d.Minutes()))
	case d < 24*time.Hour:
		return fmt.Sprintf("%dh", int(d.Hours()))
	case d < 7*24*time.Hour:
		return fmt.Sprintf("%dd", int(d.Hours()/24))
	}
	return t.Format("2 Jan 06")
}

func sym(state string) string {
	switch state {
	case "local":
		return acc.Render("↑")
	case "repo":
		return acc.Render("↓")
	}
	return faint.Render("●")
}

func (m Model) stateWords(state string) string {
	key := map[string]string{"local": "st_local", "repo": "st_repo"}[state]
	if key == "" {
		key = "st_both"
	}
	return sym(state) + " " + m.L(key)
}

// spread puts left and right at the two ends of width.
func spread(left, right string, width int) string {
	return left + strings.Repeat(" ", max(1, width-lipgloss.Width(left)-lipgloss.Width(right))) + right
}

func (m Model) header(W, ox, oy int) string {
	left := brand.Render("braingent")
	for i, k := range tabKeys {
		label := m.L(k)
		if m.counts[i] >= 0 {
			label += fmt.Sprint(" ", m.counts[i])
		}
		style := tabIdle
		if i == m.tab {
			style = tabActive
		}
		cell := style.Render(label)
		m.fr.hits.add(ox+lipgloss.Width(left), oy, lipgloss.Width(cell), target{"tab", i})
		left += cell
	}
	right := faint.Render(m.L("loading"))
	if m.st != nil {
		right = faint.Render(m.st.Phrase)
		if a := arrows(m.st.Down, m.st.Up); a != "" {
			right = acc.Render(a)
		}
		if machine := faint.Render("   ⌂ " + m.st.Machine); lipgloss.Width(left+right+machine) < W {
			right += machine
		}
	}
	return spread(left, right+" ", W)
}

// card is the bordered state across the width: the phrase and Sync, what
// moves, the chats left for bringing by hand, the update notice.
func (m Model) card(W, ox, y int) []string {
	if m.st == nil {
		return []string{faint.Render(" " + strings.Join(append([]string{m.L("loading")}, m.errs...), "  "))}
	}
	first := bold.Render(m.st.Phrase)
	if m.st.State == "pending" {
		b := button.Render(m.L("act_sync"))
		m.fr.hits.add(ox+2+lipgloss.Width(first)+3, y+1, lipgloss.Width(b), target{"sync", 0})
		first += "   " + b
	}
	body := []string{first}
	var parts []string
	for _, p := range m.st.Parts.Down {
		parts = append(parts, acc.Render("↓ ")+p)
	}
	for _, p := range m.st.Parts.Up {
		parts = append(parts, acc.Render("↑ ")+p)
	}
	if n := m.st.Chats.Up; n > 0 {
		parts = append(parts, acc.Render("↑ ")+strings.ReplaceAll(m.L("tui_n_chats"), "{n}", fmt.Sprint(n)))
	}
	if len(parts) > 0 {
		body = append(body, ansi.Truncate(strings.Join(parts, "   "), W-4, "…"))
	}
	if n := m.st.ToBring; n > 0 {
		t := strings.ReplaceAll(m.L("tui_to_bring"), "{n}", fmt.Sprint(n)) + "  →"
		m.fr.hits.add(ox+2, y+1+len(body), lipgloss.Width(t), target{"bring", 0})
		body = append(body, faint.Render(t))
	}
	if m.st.Update > 0 {
		body = append(body, acc.Render(strings.ReplaceAll(m.L("update_notice"), "{n}", fmt.Sprint(m.st.Update)))+faint.Render("  → sto update"))
	}
	return strings.Split(panel.Width(W).Render(strings.Join(body, "\n")), "\n")
}

func (m Model) chatRow(c *sto.Chat, width int, on bool) string {
	tail := ""
	if width >= 40 {
		tail = fmt.Sprintf("  %9s", ago(c.Mtime))
	}
	if width >= 60 {
		tail = fmt.Sprintf("    %-12s", ansi.Truncate(c.Machine, 12, "…")) + tail
	}
	tw := max(4, width-3-lipgloss.Width(tail))
	title := ansi.Truncate(c.Title, tw, "…")
	row := " " + sym(c.State) + " " + title + strings.Repeat(" ", max(0, tw-lipgloss.Width(title))) + faint.Render(tail)
	if on {
		return sel.Render(ansi.Strip(row))
	}
	return row
}

func (m Model) titleRow(l line, width int) string {
	t := l.project + "  ·  " + strings.ReplaceAll(m.L("tui_n_chats"), "{n}", fmt.Sprint(l.count))
	if l.here {
		t += "  ·  " + m.L("tui_here")
	}
	t = ansi.Truncate(t, width-4, "…")
	return grp.Render(" "+t) + " " + faint.Render(strings.Repeat("─", max(0, width-lipgloss.Width(t)-2)))
}

// list draws the lines that fit in height, scrolled so the cursor shows,
// recording each chat row for clicks.
func (m Model) list(width, height, ox, y int) []string {
	top := m.fr.top
	if m.cur < top {
		top = m.cur
		if top > 0 && m.lines[top-1].project != "" { // keep its group title in sight
			top--
		}
	}
	if m.cur >= top+height {
		top = m.cur - height + 1
	}
	m.fr.top = max(0, top)
	var out []string
	for i := m.fr.top; i < len(m.lines) && len(out) < height; i++ {
		l := m.lines[i]
		switch {
		case l.chat != nil:
			m.fr.hits.add(ox, y+len(out), width, target{"row", i})
			out = append(out, m.chatRow(l.chat, width, i == m.cur))
		case l.project != "":
			out = append(out, m.titleRow(l, width))
		default:
			out = append(out, "")
		}
	}
	return out
}

// side explains the selected chat and holds its one action.
func (m Model) side(width, ox, y int) []string {
	c := m.selected()
	if c == nil || m.chats == nil {
		return nil
	}
	in := width - 4 // border and padding
	folder, missing := "—", true
	if f := m.chats.Folders[c.Project]; f != nil {
		folder, missing = *f, false
	}
	field := func(k, v string) string {
		label := ansi.Truncate(m.L(k), 12, "")
		return faint.Render(label+strings.Repeat(" ", 13-lipgloss.Width(label))) + ansi.Truncate(v, max(4, in-13), "…")
	}
	out := []string{bold.Render(ansi.Truncate(c.Title, in, "…")), m.stateWords(c.State), "",
		field("tui_project", c.Project), field("tui_folder", folder),
		field("tui_machine", c.Machine), field("tui_when", ago(c.Mtime)), ""}
	if missing {
		out = append(out, acc.Render("! ")+ansi.Wrap(m.L("folder_missing"), in-2, ""), "")
	}
	key := map[string]string{"local": "k_keep", "repo": "k_bring"}[c.State]
	if key != "" {
		b := button.Render(m.L(key))
		m.fr.hits.add(ox+2, y+1+len(strings.Split(strings.Join(out, "\n"), "\n")), lipgloss.Width(b), target{"item", 0})
		out = append(out, b+faint.Render("  a"))
	}
	return out
}

func (m Model) summary(W, H, ox, oy int) string {
	s := m.st
	lines := []string{bold.Render(m.L("act_sync")), ""}
	for _, p := range s.Parts.Down {
		lines = append(lines, faint.Render(m.L("tui_will_bring")+"  ")+p)
	}
	for _, p := range s.Parts.Up {
		lines = append(lines, faint.Render(m.L("tui_will_send")+"  ")+p)
	}
	if s.Chats.Up > 0 {
		lines = append(lines, faint.Render(m.L("tui_will_send")+"  ")+strings.ReplaceAll(m.L("tui_n_chats"), "{n}", fmt.Sprint(s.Chats.Up)))
	}
	if len(lines) == 2 {
		lines = append(lines, s.Phrase)
	}
	b := button.Render(m.L("act_sync"))
	lines = append(lines, "", b+"  "+faint.Render(m.L("tui_confirm")))
	box := popup.Render(strings.Join(lines, "\n"))
	bw, bh := lipgloss.Width(box), lipgloss.Height(box)
	x0, y0 := ox+(W-bw)/2, oy+(H-bh)/2
	m.fr.hits.reset() // only the popup answers clicks while it is open
	m.fr.hits.add(x0+3, y0+2+len(lines)-1, lipgloss.Width(b), target{"confirm", 0})
	return lipgloss.Place(W, H, lipgloss.Center, lipgloss.Center, box)
}

func (m Model) footer(W int) string {
	left := faint.Render(m.L("tui_keys"))
	switch {
	case m.busy != "":
		left = acc.Render(m.busy)
	case m.flash != "" && m.failed:
		left = errStyle.Render("! " + m.flash)
	case m.flash != "":
		left = acc.Render(m.flash)
	}
	return ansi.Truncate(left, W, "…")
}

func fit(lines []string, h int) []string {
	for len(lines) < h {
		lines = append(lines, "")
	}
	return lines[:h]
}

func (m Model) View() tea.View {
	v := tea.NewView("")
	v.AltScreen, v.MouseMode = true, tea.MouseModeCellMotion
	if m.w == 0 {
		return v
	}
	m.fr.hits.reset()
	// breathing room: a line above and below, columns aside, width capped
	W, H := min(m.w-4, 150), m.h-2
	ox, oy := (m.w-W)/2, 1
	if W < 30 || H < 10 {
		v.SetContent(m.L("loading"))
		return v
	}
	out := []string{m.header(W, ox, oy), ""}
	out = append(out, m.card(W, ox, oy+len(out))...)
	out = append(out, "")
	listH, y := H-len(out)-2, oy+len(out)
	if m.tab != tChats || m.chats == nil {
		out = append(out, fit([]string{faint.Render(" " + m.L(map[bool]string{true: "empty", false: "loading"}[m.chats != nil]))}, listH)...)
	} else if W >= 90 {
		sideW := min(48, W*2/5)
		listW := W - sideW - 2
		list := strings.Join(fit(m.list(listW, listH, ox, y), listH), "\n")
		side := panel.Width(sideW).Height(listH).MaxHeight(listH).Render(strings.Join(m.side(sideW, ox+listW+2, y), "\n"))
		out = append(out, strings.Split(lipgloss.JoinHorizontal(lipgloss.Top, lipgloss.NewStyle().Width(listW).Render(list), "  ", side), "\n")...)
	} else {
		out = append(out, fit(m.list(W, listH, ox, y), listH)...)
	}
	out = append(fit(out, H-1), m.footer(W))
	content := strings.Join(out, "\n")
	if m.confirm && m.st != nil {
		content = m.summary(W, H, ox, oy)
	}
	v.SetContent(lipgloss.NewStyle().MarginTop(oy).MarginLeft(ox).Render(content))
	return v
}
