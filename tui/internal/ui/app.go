// Package ui is the braingent TUI: a header with the tabs and the sync
// state, a card with the one Sync button, and each tab's list beside a
// sidebar that explains the selected item. Every number and word comes from
// `sto data`; this package only lays them out.
package ui

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/glamour/v2"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"

	"github.com/SimonOcampo1/braingent-sto/tui/internal/sto"
)

const (
	tChats = iota
	tMemories
	tTools
	tSettings
	tSearch // not a tab: the results of `/`, shown in place of the tab's list
)

var tabKeys = [4]string{"tui_chats", "tui_memories", "tui_tools", "tui_settings"}

type loaded struct {
	view string
	v    any
	err  error
}

type stepMsg string

type tickMsg struct{}

// searchAfter fires once typing pauses; seq is the keystroke it waited for,
// so a pause a later key superseded does nothing.
type searchAfter struct{ seq int }

// searched is a search's answer, tagged with the query's seq so an answer
// to an older query is dropped.
type searched struct {
	seq int
	v   *sto.Search
	err error
}

// searchPause is how long typing must stop before the search runs: each one
// costs half a second of the engine, so not one per letter.
const searchPause = 200 * time.Millisecond

// spinner turns beside the footer's progress while an act runs.
var spinner = []string{"◐", "◓", "◑", "◒"}

func tick() tea.Cmd {
	return tea.Tick(120*time.Millisecond, func(time.Time) tea.Msg { return tickMsg{} })
}

type actDone struct {
	msg string
	err error
}

// frame is what View learns about the screen and Update needs back: where
// each clickable thing is, and how far each list is scrolled. View has a
// value receiver, so it lives behind a pointer.
type frame struct {
	hits hits
	top  [5]int
}

type list struct {
	lines []line
	cur   int
}

// reader is a chat, a memory or a note open full screen.
type reader struct {
	title, md, err string
	turns          []sto.Turn
	lines          []string
	width, top     int
}

// Model is the whole TUI state.
type Model struct {
	c   sto.Client
	cwd string

	w, h   int
	tab    int
	st     *sto.Status
	chats  *sto.Chats
	set    *sto.Settings
	tools  *sto.Tools
	items  [5][]item
	done   [5]bool // the list has loaded, even if it came back empty
	lists  [5]list
	counts [4]int // -1 until loaded; Settings has none
	errs   []string

	grouped bool
	alpha   bool   // A-Z instead of newest first
	kind    string // the search results' filter: "" for all, or a kinds entry

	searching  bool // the results of `/` replace the tab's list
	typing     bool // the query is being written
	query      string
	seq        int                // bumped by every keystroke and every search
	searchBusy bool               // a search is running; its last results stay
	cancel     context.CancelFunc // kills the running search

	read *reader

	confirm  bool            // the Sync summary is open
	marked   map[string]bool // delete targets (kind:name) picked with x
	ask      *folderAsk      // the folder of a project, being typed
	updating bool            // the question before applying a new braingent version
	limits   []sto.Limit
	del      *deletion // the question of where to delete, while it is open
	busy     string    // progress of a running act; keys wait while it is set
	flash    string
	failed   bool
	spin     int // the frame of the spinner beside busy
	ch       chan tea.Msg
	folded   [5]map[string]bool
	fr       *frame
}

// New is a TUI reading c, run from the folder cwd.
func New(c sto.Client, cwd string) Model {
	return Model{c: c, cwd: cwd, counts: [4]int{-1, -1, -1, -1}, grouped: true, fr: &frame{}}
}

func (m Model) L(key string) string { return m.st.L(key) }

func n(label string, v int) string { return strings.ReplaceAll(label, "{n}", fmt.Sprint(v)) }

func (m Model) load(view string, args ...string) tea.Cmd {
	c, cwd := m.c, m.cwd
	return func() tea.Msg {
		var v any
		switch view {
		case "status":
			v, args = &sto.Status{}, []string{"--all", "--cwd", cwd}
		case "chats":
			v = &sto.Chats{}
		case "memories":
			v = &sto.Memories{}
		case "tools":
			v = &sto.Tools{}
		case "settings":
			v = &sto.Settings{}
		case "usage": // its own call: the usage API is slow, the status is not
			v = &sto.Usage{}
		case "search":
			v = &sto.Search{}
		case "detail":
			v = &sto.Detail{}
		}
		return loaded{view, v, c.Data(v, view, args...)}
	}
}

func (m Model) loadAll() tea.Cmd {
	return tea.Batch(m.load("status"), m.load("chats"), m.load("memories"), m.load("tools"), m.load("settings"), m.load("usage"))
}

func (m Model) Init() tea.Cmd { return m.loadAll() }

func listen(ch chan tea.Msg) tea.Cmd { return func() tea.Msg { return <-ch } }

// act runs `sto act args...`, its progress arriving as stepMsg and its end
// as actDone; busy is what the footer says meanwhile.
func (m *Model) act(busy string, args ...string) tea.Cmd {
	c, ch := m.c, make(chan tea.Msg, 16)
	m.ch, m.busy, m.flash = ch, busy, ""
	go func() {
		msg, err := c.Act(func(s string) { ch <- stepMsg(s) }, args...)
		ch <- actDone{msg, err}
	}()
	return tea.Batch(listen(ch), tick())
}

func (m *Model) settingItems() []item {
	if m.set == nil {
		return nil
	}
	prefs, here, mods, cloud := m.L("sec_prefs"), m.L("tui_machine"), m.L("sec_modules"), m.L("sec_remote")
	its := []item{
		{kind: "setting", id: "lang", title: m.L("language"), group: prefs},
		{kind: "setting", id: "accent", title: m.L("accent_color"), group: prefs},
		{kind: "setting", id: "icon", title: m.L("machine_icon"), group: here},
		{kind: "setting", id: "color", title: m.L("machine_color"), group: here},
		{kind: "setting", id: "badge", title: m.L("badge_row"), group: here},
	}
	for _, md := range m.set.Modules {
		its = append(its, item{kind: "setting", id: "module:" + md.ID, title: md.ID, group: mods})
	}
	its = append(its, item{kind: "setting", id: "cloud", title: m.L("cloud_is_repo"), group: cloud, desc: m.set.Cloud})
	for i := range its {
		if _, cur, labels := m.choices(its[i].id); len(labels) > 0 {
			its[i].sub = cur
		}
	}
	return its
}

// choices is what a setting can be: the values `sto act set` takes, the
// current one shown, and how each value reads. Empty for one that is only
// shown (the cloud's URL).
func (m Model) choices(id string) (opts []string, cur string, labels []string) {
	s := m.set
	onOff := func(on bool) ([]string, string, []string) {
		cur := m.L("off")
		if on {
			cur = m.L("on")
		}
		return []string{"on", "off"}, cur, []string{m.L("on"), m.L("off")}
	}
	switch {
	case id == "lang":
		return s.Langs, s.Lang, s.Langs
	case id == "accent":
		for _, a := range s.Accents {
			opts, labels = append(opts, a.Code), append(labels, a.Name)
			if a.Code == s.Accent {
				cur = a.Name
			}
		}
		return opts, cur, labels
	case id == "icon":
		return s.Icons, s.Look.Icon, s.Icons
	case id == "color":
		return s.Colors, s.Look.Color, s.Colors
	case id == "badge":
		return onOff(s.Badge)
	case strings.HasPrefix(id, "module:"):
		for _, md := range s.Modules {
			if "module:"+md.ID == id {
				return onOff(md.Enabled)
			}
		}
	}
	return nil, "", nil
}

// changeSetting asks `sto act set` for the setting's next value.
func (m *Model) changeSetting(id string) tea.Cmd {
	opts, cur, labels := m.choices(id)
	if len(opts) == 0 {
		return nil
	}
	next := opts[(slices.Index(labels, cur)+1)%len(opts)]
	if mod, ok := strings.CutPrefix(id, "module:"); ok {
		return m.act(m.L("loading"), "set", "module", mod, next)
	}
	return m.act(m.L("loading"), "set", id, next)
}

// rebuild lays tab t out again, keeping the cursor on the same item.
func (m *Model) rebuild(t int) {
	its, here, grouped := m.items[t], "", m.grouped
	switch t {
	case tChats:
		if m.st != nil {
			here = m.st.Project
		}
	case tSettings:
		its, grouped = m.settingItems(), true
	case tSearch:
		if m.kind != "" {
			its = slices.DeleteFunc(slices.Clone(its), func(it item) bool { return kindOf(it) != m.kind })
		}
	}
	l := &m.lists[t]
	key := l.key()
	l.lines, l.cur = arrange(its, layout{here: here, grouped: grouped, alpha: m.alpha && t != tSettings, folded: m.folded[t]}), -1
	l.pick(key)
}

// key names the line under the cursor across rebuilds: an item's id, or
// its group title's name behind a NUL no id carries.
func (l *list) key() string {
	if l.cur < 0 || l.cur >= len(l.lines) {
		return ""
	}
	if it := l.lines[l.cur].it; it != nil {
		return it.id
	}
	return "\x00" + l.lines[l.cur].group
}

// fold opens or closes the group under the cursor; all folds every group,
// or opens them all when every one is folded already.
func (m *Model) fold(all bool) {
	t := m.shown()
	if t == tSettings || !m.grouped {
		return
	}
	if m.folded[t] == nil {
		m.folded[t] = map[string]bool{}
	}
	f, l := m.folded[t], &m.lists[t]
	if all {
		open := false
		for _, it := range m.items[t] {
			open = open || !f[it.group]
		}
		for _, it := range m.items[t] {
			f[it.group] = open
		}
	} else if l.cur >= 0 && l.cur < len(l.lines) {
		g := l.lines[l.cur].group
		if it := l.lines[l.cur].it; it != nil {
			g = it.group
		}
		f[g] = !f[g]
		l.cur = slices.IndexFunc(l.lines, func(ln line) bool { return ln.it == nil && ln.group == g })
	}
	m.rebuild(t)
}

func (l *list) selected() *item {
	if l.cur >= 0 && l.cur < len(l.lines) {
		return l.lines[l.cur].it
	}
	return nil
}

// pick puts the cursor on the line with key, or on the first item, or on
// the first title when every group is folded.
func (l *list) pick(key string) {
	l.cur = -1
	for i := range l.lines {
		if l.cur = i; l.key() == key {
			return
		}
	}
	if l.cur = slices.IndexFunc(l.lines, func(ln line) bool { return ln.it != nil }); l.cur < 0 {
		l.cur = step(l.lines, -1, 1)
	}
}

// shown is the list on screen: the search results, or the tab's.
func (m *Model) shown() int {
	if m.searching {
		return tSearch
	}
	return m.tab
}

func (m *Model) cur() *list { return &m.lists[m.shown()] }

func (m *Model) selected() *item { return m.cur().selected() }

// itemAct is the one thing the selected item can do from here: keep a chat
// only on this machine, bring one only in the cloud, change a setting.
func (m *Model) itemAct() tea.Cmd {
	it := m.selected()
	if it == nil { // a group title of Chats: bring its chats only in the cloud
		if g := m.title(); g != "" && m.shown() == tChats && m.chatsIn(g, "repo") > 0 {
			return m.act(m.L("loading"), "bring-chats", g)
		}
		return nil
	}
	switch {
	case it.kind == "chat" && it.state == "local":
		return m.act(m.L("loading"), "keep", it.id)
	case it.kind == "chat" && it.state == "repo":
		return m.act(m.L("loading"), "resume", it.id)
	case (it.kind == "skill" || it.kind == "plugin") && it.state == "repo":
		return m.act(m.L("loading"), "bring", delTarget(it))
	case it.kind == "setting" && m.set != nil:
		return m.changeSetting(it.id)
	}
	return nil
}

// open is Enter: a search hit jumps to its tab, a chat, memory or note
// opens in the reader, a setting changes.
func (m *Model) open() tea.Cmd {
	it := m.selected()
	if it == nil { // a group title
		m.fold(false)
		return nil
	}
	if m.searching && it.tab >= 0 {
		m.searching, m.tab = false, it.tab
		m.lists[it.tab].pick(it.id)
		return nil
	}
	switch it.kind {
	case "chat", "memory", "note":
		m.read = &reader{title: it.title}
		return m.load("detail", it.kind, it.id)
	case "setting":
		return m.itemAct()
	}
	return nil
}

// title is the group whose title is under the cursor, or "".
func (m *Model) title() string {
	l := m.cur()
	if l.cur < 0 || l.cur >= len(l.lines) || l.lines[l.cur].it != nil {
		return ""
	}
	return l.lines[l.cur].group
}

// chatsIn counts the chats of project in state: "repo" for only in the
// cloud, "local" for only on this machine.
func (m Model) chatsIn(project, state string) int {
	k := 0
	for _, it := range m.items[tChats] {
		if it.group == project && it.state == state {
			k++
		}
	}
	return k
}

// pause schedules a search for when typing stops.
func (m *Model) pause() tea.Cmd {
	m.seq++
	seq := m.seq
	return tea.Tick(searchPause, func(time.Time) tea.Msg { return searchAfter{seq} })
}

func (m *Model) stopSearch() {
	if m.cancel != nil {
		m.cancel()
	}
	m.searchBusy = false
}

// search runs the query now, killing the one still running. Under two
// letters it clears the results instead: one letter matches everything.
func (m *Model) search() tea.Cmd {
	m.stopSearch()
	m.seq++
	if len([]rune(strings.TrimSpace(m.query))) < 2 {
		m.items[tSearch], m.done[tSearch] = nil, false
		m.rebuild(tSearch)
		return nil
	}
	ctx, cancel := context.WithCancel(context.Background())
	seq, q, c, ticking := m.seq, m.query, m.c, m.busy != ""
	m.cancel, m.searchBusy = cancel, true
	run := func() tea.Msg {
		s := &sto.Search{}
		return searched{seq, s, c.DataCtx(ctx, s, "search", "--q", q)}
	}
	if ticking {
		return run
	}
	return tea.Batch(run, tick())
}

// folderAsk is the folder of a project being typed in the footer.
type folderAsk struct{ project, value string }

// askFolder starts typing the folder of the project under the cursor, from
// the one it has or from where the TUI runs.
func (m *Model) askFolder() {
	if m.shown() != tChats || m.chats == nil {
		return
	}
	p := m.title()
	if it := m.selected(); it != nil {
		p = it.group
	}
	if p == "" {
		return
	}
	v := m.cwd
	if f := m.chats.Folders[p]; f != nil {
		v = *f
	}
	m.ask = &folderAsk{project: p, value: v}
}

// deletion is what d is about to delete, waiting for where: this machine
// only, or everywhere. here is false when a memory is among the targets.
type deletion struct {
	targets, titles []string
	here            bool
}

// delTarget is what `sto act delete` takes for an item, or "" when the item
// cannot be deleted (a setting, a vault note).
func delTarget(it *item) string {
	switch it.kind {
	case "chat", "memory", "plugin":
		return it.kind + ":" + it.id
	case "skill":
		return "skill:" + it.title
	}
	return ""
}

// mark toggles the item under the cursor in the set d deletes.
func (m *Model) mark() {
	if it := m.selected(); it != nil && delTarget(it) != "" {
		if m.marked == nil {
			m.marked = map[string]bool{}
		}
		if t := delTarget(it); m.marked[t] {
			delete(m.marked, t)
		} else {
			m.marked[t] = true
		}
	}
}

// askDelete opens the question for the marked items, or for the one under
// the cursor when nothing is marked.
func (m *Model) askDelete() {
	titles := map[string]string{}
	for t := range tSearch + 1 {
		for _, it := range m.items[t] {
			titles[delTarget(&it)] = it.title
		}
	}
	var targets []string
	for t := range m.marked {
		targets = append(targets, t)
	}
	slices.Sort(targets)
	if len(targets) == 0 {
		if it := m.selected(); it != nil && delTarget(it) != "" {
			targets = []string{delTarget(it)}
			titles[targets[0]] = it.title
		}
	}
	if len(targets) == 0 {
		return
	}
	d := &deletion{targets: targets, here: true}
	for _, t := range targets {
		d.titles = append(d.titles, titles[t])
		d.here = d.here && !strings.HasPrefix(t, "memory:")
	}
	m.del = d
}

// deleteNow runs the deletion where the answer said.
func (m *Model) deleteNow(everywhere bool) tea.Cmd {
	if !everywhere && !m.del.here {
		return nil
	}
	scope := map[bool]string{true: "everywhere", false: "here"}[everywhere]
	targets := m.del.targets
	m.del, m.marked = nil, nil
	return m.act(m.L("loading"), append([]string{"delete", "--scope", scope}, targets...)...)
}

func (m *Model) openSync() {
	if m.st != nil && m.st.State == "pending" {
		m.confirm = true
	}
}

func (m *Model) move(d int) {
	if m.read != nil {
		m.read.top = max(0, m.read.top+d)
		return
	}
	l := m.cur()
	for range max(d, -d) {
		l.cur = step(l.lines, l.cur, max(-1, min(1, d)))
	}
}

func (m *Model) relabelTools() {
	if m.tools == nil {
		return
	}
	m.items[tTools] = toolItems(m.tools, m.L("tab_skills"), m.L("tui_plugins"))
	m.counts[tTools], m.done[tTools] = len(m.items[tTools]), true
	m.rebuild(tTools)
}

func (m Model) loadedMsg(msg loaded) (Model, tea.Cmd) {
	if msg.err != nil {
		if msg.view == "detail" && m.read != nil {
			m.read.err = msg.err.Error()
		} else {
			m.errs = append(m.errs, msg.view+": "+msg.err.Error())
		}
		return m, nil
	}
	switch v := msg.v.(type) {
	case *sto.Status:
		m.st = v
		setAccent(v.Accent)
		m.relabelTools() // its group titles are labels
		m.rebuild(tChats)
		m.rebuild(tSettings)
	case *sto.Chats:
		m.chats, m.counts[tChats], m.items[tChats], m.done[tChats] = v, len(v.Rows), chatItems(v), true
		m.rebuild(tChats)
	case *sto.Memories:
		m.items[tMemories] = memoryItems(v)
		m.counts[tMemories], m.done[tMemories] = len(m.items[tMemories]), true
		m.rebuild(tMemories)
	case *sto.Tools:
		m.tools = v
		m.relabelTools()
	case *sto.Settings:
		m.set, m.done[tSettings] = v, true
		m.rebuild(tSettings)
	case *sto.Usage:
		m.limits = v.Limits
	case *sto.Detail:
		if m.read != nil {
			m.read.title, m.read.md, m.read.turns = v.Title, v.Markdown, v.Turns
		}
	}
	return m, nil
}

func (m Model) keyMsg(msg tea.KeyPressMsg) (Model, tea.Cmd) {
	k := msg.String()
	m.flash = ""
	switch {
	case m.ask != nil:
		switch k {
		case "esc":
			m.ask = nil
		case "enter":
			a := m.ask
			m.ask = nil
			return m, m.act(m.L("loading"), "set-folder", a.project, a.value)
		case "backspace":
			if r := []rune(m.ask.value); len(r) > 0 {
				m.ask.value = string(r[:len(r)-1])
			}
		case "ctrl+u":
			m.ask.value = ""
		default:
			m.ask.value += msg.Text
		}
		return m, nil
	case m.updating:
		m.updating = false
		if k == "enter" {
			return m, m.act(m.L("update_available"), "update")
		}
		return m, nil
	case m.del != nil:
		switch k {
		case "1":
			return m, m.deleteNow(false)
		case "2":
			return m, m.deleteNow(true)
		case "esc", "q":
			m.del = nil
		}
		return m, nil
	case m.confirm:
		m.confirm = false
		if k == "enter" {
			return m, m.act(m.L("mod_syncing"), "sync", "--all")
		}
		return m, nil
	case m.typing:
		switch k {
		case "esc":
			m.typing, m.searching = false, false
			m.stopSearch()
		case "enter": // stop typing, move among the results
			if m.typing = false; strings.TrimSpace(m.query) == "" {
				m.searching = false
			}
			return m, m.search()
		case "down", "up":
			m.move(map[string]int{"down": 1, "up": -1}[k])
		case "backspace":
			if r := []rune(m.query); len(r) > 0 {
				m.query = string(r[:len(r)-1])
				return m, m.pause()
			}
		default:
			if msg.Text != "" {
				m.query += msg.Text
				return m, m.pause()
			}
		}
		return m, nil
	case m.read != nil:
		switch k {
		case "esc", "q", "left", "h":
			m.read = nil
		case "j", "down":
			m.move(1)
		case "k", "up":
			m.move(-1)
		case "space", "pgdown", "f":
			m.move(max(1, m.h-6))
		case "b", "pgup":
			m.move(-max(1, m.h-6))
		case "g", "home":
			m.read.top = 0
		case "G", "end":
			m.read.top = len(m.read.lines)
		}
		return m, nil
	}
	switch k {
	case "q":
		return m, tea.Quit
	case "tab":
		m.tab, m.searching = (m.tab+1)%len(tabKeys), false
	case "shift+tab":
		m.tab, m.searching = (m.tab+len(tabKeys)-1)%len(tabKeys), false
	case "j", "down":
		m.move(1)
	case "k", "up":
		m.move(-1)
	case "pgdown":
		m.move(10)
	case "pgup":
		m.move(-10)
	case "home":
		m.cur().cur = step(m.cur().lines, -1, 1)
	case "end":
		m.cur().cur = step(m.cur().lines, len(m.cur().lines), -1)
	case "s":
		m.alpha = !m.alpha
		for t := range tSearch + 1 {
			m.rebuild(t)
		}
	case "f":
		if m.searching {
			m.kind = kinds[(slices.Index(kinds, m.kind)+1)%len(kinds)]
			m.rebuild(tSearch)
		}
	case "enter":
		return m, m.open()
	case "/":
		m.searching, m.typing, m.query = true, true, ""
	case "space", " ":
		m.fold(false)
	case "c":
		m.fold(true)
	case "b":
		m.grouped = !m.grouped
		for t := range tSettings {
			m.rebuild(t)
		}
	case "w":
		m.askFolder()
	case "u":
		m.updating = m.st != nil && m.st.Update > 0
	case "g":
		return m, m.act(m.L("loading"), "graph")
	case "x":
		m.mark()
	case "d":
		m.askDelete()
	case "a":
		return m, m.itemAct()
	case "S":
		m.openSync()
	case "esc":
		m.searching, m.marked = false, nil
	}
	return m, nil
}

func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.w, m.h = msg.Width, msg.Height
	case loaded:
		return m.loadedMsg(msg)
	case searchAfter:
		if msg.seq == m.seq {
			return m, m.search()
		}
	case searched:
		if msg.seq != m.seq {
			break
		}
		m.searchBusy = false
		if msg.err != nil {
			m.flash, m.failed = msg.err.Error(), true
			break
		}
		m.items[tSearch], m.done[tSearch] = hitItems(msg.v.Hits, m.tab, m.L("tui_tools"), m.L("tui_notes")), true
		m.rebuild(tSearch)
	case tickMsg:
		if m.busy != "" || m.searchBusy {
			m.spin++
			return m, tick()
		}
	case stepMsg:
		m.busy = string(msg)
		return m, listen(m.ch)
	case actDone:
		m.busy, m.flash, m.failed = "", msg.msg, msg.err != nil
		if msg.err != nil {
			m.flash = msg.err.Error()
		}
		return m, m.loadAll()
	case tea.KeyPressMsg:
		if msg.String() == "ctrl+c" {
			return m, tea.Quit
		}
		if m.busy != "" {
			break
		}
		return m.keyMsg(msg)
	case tea.MouseWheelMsg:
		d := 1
		if msg.Button == tea.MouseWheelUp {
			d = -1
		}
		if m.read != nil {
			d *= 3
		}
		m.move(d)
	case tea.MouseClickMsg:
		if m.busy != "" || m.read != nil {
			break
		}
		t, ok := m.fr.hits.at(msg.X, msg.Y)
		if m.del != nil {
			switch {
			case ok && t.kind == "delhere":
				return m, m.deleteNow(false)
			case ok && t.kind == "delall":
				return m, m.deleteNow(true)
			case !ok:
				m.del = nil
			}
			break
		}
		if m.confirm {
			m.confirm = false
			if ok && t.kind == "confirm" {
				return m, m.act(m.L("mod_syncing"), "sync", "--all")
			}
			break
		}
		switch t.kind {
		case "tab":
			m.tab, m.searching, m.typing = t.i, false, false
		case "row":
			if m.cur().cur = t.i; m.selected() == nil {
				m.fold(false)
			}
		case "sync":
			m.openSync()
		case "item":
			return m, m.itemAct()
		case "fold":
			m.fold(false)
		case "folder":
			m.askFolder()
		case "kind":
			m.kind = kinds[t.i]
			m.rebuild(tSearch)
		case "open":
			return m, m.open()
		}
	}
	return m, nil
}

// ---------- view ----------

func ago(ts float64) string {
	if ts == 0 {
		return ""
	}
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
	case "gone":
		return acc.Render("×")
	case "both":
		return faint.Render("●")
	}
	return " "
}

func (m Model) stateWords(state string) string {
	key := map[string]string{"local": "st_local", "repo": "st_repo", "gone": "st_gone", "both": "st_both"}[state]
	if key == "" {
		return ""
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
		if i == m.tab && !m.searching {
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
	// the Sync button is a block at the card's right, as tall as the card:
	// it is the one thing on the screen to press (its key, S, is in the footer)
	var btn string
	if m.st.State == "pending" {
		btn = bigButton.Render(m.L("act_sync"))
	}
	inW := W - 4 - lipgloss.Width(btn) - 2*min(1, lipgloss.Width(btn))
	body := []string{bold.Render(m.st.Phrase)}
	var parts []string
	for _, p := range m.st.Parts.Down {
		parts = append(parts, acc.Render("↓ ")+p)
	}
	for _, p := range m.st.Parts.Up {
		parts = append(parts, acc.Render("↑ ")+p)
	}
	if v := m.st.Chats.Up; v > 0 {
		parts = append(parts, acc.Render("↑ ")+n(m.L("tui_n_chats"), v))
	}
	if len(parts) > 0 {
		body = append(body, ansi.Truncate(strings.Join(parts, "   "), inW, "…"))
	}
	if m.st.Update > 0 {
		body = append(body, ansi.Truncate(acc.Render(n(m.L("update_notice"), m.st.Update))+faint.Render("  → u"), inW, "…"))
	}
	inner := strings.Join(body, "\n")
	if btn != "" {
		h := max(len(body), 3)
		btn = bigButton.Height(h).Render(m.L("act_sync"))
		bx := ox + 2 + inW + 2
		for r := range h {
			m.fr.hits.add(bx, y+1+r, lipgloss.Width(btn), target{"sync", 0})
		}
		inner = lipgloss.JoinHorizontal(lipgloss.Top, lipgloss.NewStyle().Width(inW).Height(h).Render(inner), "  ", btn)
	}
	return strings.Split(panel.Width(W).Render(inner), "\n")
}

// tail is the item's columns after the title, each with its width; they
// are dropped from the left when the list is narrow.
func tail(it *item, hit bool) ([]string, []int) {
	switch it.kind {
	case "chat":
		if hit { // a search hit: its project, not its machine
			return []string{it.sub}, []int{18}
		}
		return []string{it.sub, ago(it.mtime)}, []int{12, 9}
	case "memory":
		if it.mtime == 0 {
			return []string{it.sub}, []int{18}
		}
		return []string{it.sub, ago(it.mtime)}, []int{10, 9}
	case "setting":
		return []string{it.sub}, []int{14}
	case "note":
		return []string{it.sub}, []int{18}
	}
	return []string{it.sub}, []int{18}
}

func (m Model) row(it *item, width int, on bool) string {
	cols, ws := tail(it, m.searching)
	if m.searching && m.grouped { // the group title already names the project
		cols, ws = []string{it.kind}, []int{8}
	} else if m.searching {
		cols, ws = append([]string{it.kind}, cols...), append([]int{8}, ws...)
	}
	for len(cols) > 0 && width-3-sum(ws)-4*len(ws) < 16 {
		cols, ws = cols[1:], ws[1:]
	}
	t := ""
	for i, c := range cols {
		t += "    " + fmt.Sprintf("%*s", ws[i], ansi.Truncate(c, ws[i], "…"))
	}
	lead := " "
	if m.grouped && m.shown() != tSettings { // a row sits indented under its group's title
		lead = "   "
	}
	if m.marked[delTarget(it)] { // marked for d: a square inside the indent
		lead = map[bool]string{true: " " + acc.Render("■") + " ", false: acc.Render("■")}[len(lead) == 3]
	}
	tw := max(4, width-lipgloss.Width(lead)-2-lipgloss.Width(t))
	title := ansi.Truncate(it.title, tw, "…")
	r := lead + sym(it.state) + " " + title + strings.Repeat(" ", max(0, tw-lipgloss.Width(title))) + faint.Render(t)
	if on {
		return sel.Render(ansi.Strip(r))
	}
	return r
}

func sum(xs []int) (s int) {
	for _, x := range xs {
		s += x
	}
	return
}

func (m Model) titleRow(l line, width int, on bool) string {
	mark := "▼ "
	if l.folded {
		mark = "▶ "
	}
	count, moves := fmt.Sprint(l.count), ""
	if m.shown() == tChats {
		count = n(m.L("tui_n_chats"), l.count)
		// ↑ to send, ↓ to bring: the only colour on the line
		moves = strings.TrimSpace(arrows(0, m.chatsIn(l.group, "local")) + " " + arrows(m.chatsIn(l.group, "repo"), 0))
	}
	// fixed columns at the right, so every title's numbers line up
	right := fmt.Sprintf("%10s  %-11s", count, moves)
	here := ""
	if l.here {
		here = "  ⌂ " + m.L("tui_here")
	}
	name := ansi.Truncate(l.group, max(4, width-lipgloss.Width(right)-lipgloss.Width(here)-5), "…")
	gap := strings.Repeat(" ", max(1, width-3-lipgloss.Width(name+here)-lipgloss.Width(right)))
	if on {
		return sel.Render(" " + mark + name + here + gap + right)
	}
	return faint.Render(" "+mark) + grp.Render(name) + faint.Render(here) + gap +
		faint.Render(fmt.Sprintf("%10s  ", count)) + acc.Render(fmt.Sprintf("%-11s", moves))
}

// list draws the lines that fit in height, scrolled so the cursor shows,
// recording each item row for clicks.
func (m Model) list(width, height, ox, y int) []string {
	t := m.shown()
	l := m.lists[t]
	if len(l.lines) == 0 {
		msg := m.L("loading")
		if t == tSearch && len([]rune(strings.TrimSpace(m.query))) < 2 {
			msg = m.L("tui_two_letters")
		} else if m.done[t] {
			msg = m.L("empty")
		}
		return []string{faint.Render(" " + msg)}
	}
	top := m.fr.top[t]
	if l.cur < top {
		top = l.cur
		if top > 0 && l.lines[top-1].group != "" { // keep its group title in sight
			top--
		}
	}
	if l.cur >= top+height {
		top = l.cur - height + 1
	}
	top = max(0, min(top, len(l.lines)-1))
	m.fr.top[t] = top
	var out []string
	for i := top; i < len(l.lines) && len(out) < height; i++ {
		ln := l.lines[i]
		switch {
		case ln.it != nil:
			m.fr.hits.add(ox, y+len(out), width, target{"row", i})
			out = append(out, m.row(ln.it, width, i == l.cur))
		case ln.group != "":
			m.fr.hits.add(ox, y+len(out), width, target{"row", i})
			out = append(out, m.titleRow(ln, width, i == l.cur))
		default:
			out = append(out, "")
		}
	}
	return out
}

// side explains the selected item and holds its actions as buttons.
func (m Model) side(width, ox, y int) []string {
	it := m.selected()
	in := width - 4 // border and padding
	if it == nil {  // a group title: what it holds and how to open it
		l := m.cur()
		if l.cur < 0 || l.cur >= len(l.lines) {
			return nil
		}
		g := l.lines[l.cur]
		b := button.Render(m.L("tui_fold"))
		m.fr.hits.add(ox+2, y+1+3, lipgloss.Width(b), target{"fold", 0})
		out := []string{bold.Render(ansi.Truncate(g.group, in, "…")), faint.Render(fmt.Sprint(g.count)), "",
			b + faint.Render("  ↵ / space"), "", faint.Render("c  " + m.L("tui_fold_all"))}
		if k := m.chatsIn(g.group, "repo"); m.shown() == tChats && k > 0 {
			bb := button.Render(n(m.L("tui_bring_n"), k))
			m.fr.hits.add(ox+2, y+1+len(out)+1, lipgloss.Width(bb), target{"item", 0})
			out = append(out, "", bb+faint.Render("  a"))
			if m.chats != nil && m.chats.Folders[g.group] == nil {
				out = append(out, "", acc.Render("! ")+ansi.Wrap(m.L("folder_missing"), in-2, ""))
			}
		}
		return out
	}
	field := func(k, v string) string {
		label := ansi.Truncate(m.L(k), 12, "")
		return faint.Render(label+strings.Repeat(" ", 13-lipgloss.Width(label))) + ansi.Truncate(v, max(4, in-13), "…")
	}
	wrap := func(s string) string { return ansi.Wrap(s, in, "") }
	out := []string{bold.Render(ansi.Truncate(it.title, in, "…"))}
	if w := m.stateWords(it.state); w != "" {
		out = append(out, w)
	}
	out = append(out, "")
	var buttons []target
	var labels []string
	btn := func(label string, t target) { labels, buttons = append(labels, label), append(buttons, t) }
	switch {
	case m.searching:
		out = append(out, faint.Render(it.kind+"  ·  "+it.sub))
		btn("↵ "+m.L("tui_goto"), target{"open", 0})
	case it.kind == "chat":
		folder, missing := "—", true
		if f := m.chats.Folders[it.group]; f != nil {
			folder, missing = *f, false
		}
		out = append(out, field("tui_project", it.group), field("tui_folder", folder),
			field("tui_machine", it.sub), field("tui_when", ago(it.mtime)), "")
		if missing {
			out = append(out, acc.Render("! ")+ansi.Wrap(m.L("folder_missing"), in-2, ""), "")
			btn(m.L("tui_choose_folder")+"  w", target{"folder", 0})
		}
		btn("↵ "+m.L("tui_read"), target{"open", 0})
		if key := map[string]string{"local": "k_keep", "repo": "k_bring"}[it.state]; key != "" {
			btn(m.L(key), target{"item", 0})
		}
	case it.kind == "memory":
		out = append(out, field("tui_project", it.group), field("tui_when", ago(it.mtime)), "", wrap(it.desc), "")
		btn("↵ "+m.L("tui_read"), target{"open", 0})
	case it.kind == "setting" && m.set != nil:
		_, cur, labels := m.choices(it.id)
		if len(labels) == 0 { // shown, not changed: the cloud's URL
			out = append(out, wrap(it.desc))
			break
		}
		for _, c := range labels {
			if c == cur {
				out = append(out, acc.Render("● ")+c)
			} else {
				out = append(out, faint.Render("  "+c))
			}
		}
		out = append(out, "")
		btn(m.L("tui_change"), target{"item", 0})
	default:
		out = append(out, wrap(strings.Trim(it.desc, `"`)))
	}
	if len(buttons) > 0 {
		row, x := "", 0
		by := y + 1 + len(strings.Split(strings.Join(out, "\n"), "\n"))
		for i, label := range labels {
			b := button.Render(label)
			m.fr.hits.add(ox+2+x, by, lipgloss.Width(b), buttons[i])
			row += b + " "
			x += lipgloss.Width(b) + 1
		}
		out = append(out, row)
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
		lines = append(lines, faint.Render(m.L("tui_will_send")+"  ")+n(m.L("tui_n_chats"), s.Chats.Up))
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

// deleteBox asks where to delete: this machine only, or everywhere.
func (m Model) deleteBox(W, H, ox, oy int) string {
	d := m.del
	lines := []string{bold.Render(n(m.L("tui_del_title"), len(d.targets))), ""}
	for i, t := range d.titles {
		if i == 8 {
			lines = append(lines, faint.Render(fmt.Sprintf("… +%d", len(d.titles)-8)))
			break
		}
		lines = append(lines, "  "+ansi.Truncate(t, 60, "…"))
	}
	lines = append(lines, "")
	here := button.Render("1  " + m.L("tui_del_here"))
	if !d.here {
		here = faint.Render(" 1  " + m.L("tui_del_here") + " ")
	}
	all := button.Render("2  " + m.L("tui_del_everywhere"))
	row := len(lines)
	lines = append(lines, here+"  "+all+"   "+faint.Render("esc"), "")
	if !d.here {
		lines = append(lines, faint.Render(ansi.Wrap(m.L("del_memory_here"), 56, "")))
	}
	lines = append(lines, faint.Render(ansi.Wrap(m.L("tui_del_note"), 56, "")))
	box := popup.Render(strings.Join(lines, "\n"))
	bw, bh := lipgloss.Width(box), lipgloss.Height(box)
	x0, y0 := ox+(W-bw)/2, oy+(H-bh)/2
	m.fr.hits.reset()
	if d.here {
		m.fr.hits.add(x0+3, y0+2+row, lipgloss.Width(here), target{"delhere", 0})
	}
	m.fr.hits.add(x0+3+lipgloss.Width(here)+2, y0+2+row, lipgloss.Width(all), target{"delall", 0})
	return lipgloss.Place(W, H, lipgloss.Center, lipgloss.Center, box)
}

// page is the reader: the markdown rendered once per width, scrolled.
func (m Model) page(W, H int) string {
	r := m.read
	body := []string{faint.Render(" " + m.L("loading"))}
	switch {
	case r.err != "":
		body = []string{errStyle.Render(" ! " + r.err)}
	case r.md != "" || len(r.turns) > 0:
		if r.width != W {
			r.width, r.lines = W, m.render(r, W)
		}
		r.top = max(0, min(r.top, len(r.lines)-(H-3)))
		body = r.lines[r.top:min(len(r.lines), r.top+H-3)]
	}
	head := spread(brand.Render("braingent")+bold.Render(ansi.Truncate(r.title, W-30, "…")),
		faint.Render(fmt.Sprintf("%d/%d ", min(r.top+H-3, len(r.lines)), len(r.lines))), W)
	return strings.Join(append(append([]string{head, ""}, fit(body, H-3)...), m.hints("j k", "tui_k_scroll", "space", "tui_k_page", "home end", "tui_k_ends", "esc", "tui_k_back")), "\n")
}

// render lays the reader's text out at width W, through Glamour. A chat's
// turns each get a bar down their left edge: the accent's ▌ for yours, a
// faint │ for Claude's, under the name of who spoke.
func (m Model) render(r *reader, W int) []string {
	w := W - 4
	if len(r.turns) > 0 {
		w = W - 8 // the bar and Glamour's own margin
	}
	gr, err := glamour.NewTermRenderer(glamour.WithStandardStyle("dark"), glamour.WithWordWrap(max(20, w)))
	md := func(text string) []string {
		if err == nil {
			if s, err := gr.Render(text); err == nil {
				text = strings.Trim(s, "\n")
			}
		}
		return strings.Split(text, "\n")
	}
	if len(r.turns) == 0 {
		return md(r.md)
	}
	var out []string
	for _, t := range r.turns {
		bar, who := faint.Render("│ "), bold.Render(m.L("tui_claude"))
		if t.Who == "user" {
			bar, who = acc.Render("▌ "), acc.Bold(true).Render(m.L("tui_you"))
		}
		out = append(out, bar+who)
		for _, l := range md(t.Markdown) {
			out = append(out, bar+l)
		}
		out = append(out, "")
	}
	return out
}

// kinds are the search filter's choices, in the order f cycles them.
var kinds = []string{"", "chat", "memory", "tool", "note"}

var kindLabels = map[string]string{"": "tui_all", "chat": "tui_chats", "memory": "tui_memories", "tool": "tui_tools", "note": "tui_notes"}

// kindOf is the filter a search hit answers to: skills and plugins are tools.
func kindOf(it item) string {
	if it.kind == "skill" || it.kind == "plugin" {
		return "tool"
	}
	return it.kind
}

// chips is the search filter as a row of clickable choices.
func (m Model) chips(ox, y int) string {
	out := " "
	for i, k := range kinds {
		style := tabIdle
		if k == m.kind {
			style = tabActive
		}
		c := style.Render(m.L(kindLabels[k]))
		m.fr.hits.add(ox+lipgloss.Width(out), y, lipgloss.Width(c), target{"kind", i})
		out += c + " "
	}
	return out + faint.Render(" f")
}

// hints is a line of keys and what they do: the key in the accent, the
// words faint, so the two never read as one.
func (m Model) hints(pairs ...string) string {
	var out []string
	for i := 0; i+1 < len(pairs); i += 2 {
		out = append(out, keyStyle.Render(pairs[i])+" "+faint.Render(m.L(pairs[i+1])))
	}
	return strings.Join(out, "   ")
}

func (m Model) footer(W int) string {
	sort := "tui_sort_az"
	if m.alpha {
		sort = "tui_sort_new"
	}
	left := m.hints("j k", "tui_k_move", "↵", "tui_read", "/", "tui_search", "a", "tui_k_action",
		"S", "act_sync", "x", "tui_k_mark", "d", "tui_k_delete", "space", "tui_k_fold", "c", "tui_k_fold_all", "s", sort, "b", "tui_k_group",
		"w", "tui_k_folder", "g", "tui_k_graph", "tab", "tui_k_view", "q", "tui_k_quit")
	if m.st != nil && m.st.Update > 0 { // the one key worth reading first when it applies
		left = m.hints("u", "tui_k_update") + "   " + left
	}
	switch {
	case m.ask != nil:
		left = faint.Render(m.L("tui_folder_of")+" "+m.ask.project+": ") + m.ask.value + acc.Render("█") +
			"   " + m.hints("↵", "tui_k_save", "esc", "tui_k_close")
	case m.typing:
		left = acc.Render("/ ") + m.query + acc.Render("█")
		if m.searchBusy {
			left += "  " + acc.Render(spinner[m.spin%len(spinner)])
		}
		left += "   " + m.hints("↵", "tui_k_results", "esc", "tui_k_close")
	case m.busy != "":
		left = acc.Render(spinner[m.spin%len(spinner)] + " " + m.busy)
	case m.flash != "" && m.failed:
		left = errStyle.Render("! " + m.flash)
	case m.flash != "":
		left = acc.Render(m.flash)
	case m.searching:
		left = acc.Render("/ "+m.query) + "   " + m.hints("↵", "tui_goto", "f", "tui_k_filter",
			"space", "tui_k_fold", "s", sort, "esc", "tui_k_close")
	}
	right := m.usage()
	return spread(ansi.Truncate(left, max(10, W-lipgloss.Width(right)-3), "…"), faint.Render(right), W)
}

// usage is the plan's limits as the band shows them: "5h 34% · wk 61%".
func (m Model) usage() string {
	var parts []string
	for _, l := range m.limits {
		switch l.Kind {
		case "session":
			parts = append(parts, fmt.Sprintf("%s %d%%", m.L("mod_5h"), l.Percent))
		case "weekly_all":
			parts = append(parts, fmt.Sprintf("%s %d%%", m.L("mod_week"), l.Percent))
		}
	}
	return strings.Join(parts, " · ")
}

// updateBox asks before applying a new braingent version, showing what it brings.
func (m Model) updateBox(W, H int) string {
	lines := []string{bold.Render(m.L("update_available") + fmt.Sprintf(" · %d", m.st.Update)), ""}
	for _, l := range m.st.UpdateLog {
		lines = append(lines, faint.Render(ansi.Truncate(l, 70, "…")))
	}
	lines = append(lines, "", m.hints("↵", "tui_k_apply", "esc", "tui_k_close"))
	return lipgloss.Place(W, H, lipgloss.Center, lipgloss.Center, popup.Render(strings.Join(lines, "\n")))
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
	var content string
	switch {
	case m.read != nil:
		content = m.page(W, H)
	case m.del != nil:
		content = m.deleteBox(W, H, ox, oy)
	case m.updating:
		content = m.updateBox(W, H)
	case m.confirm && m.st != nil:
		content = m.summary(W, H, ox, oy)
	default:
		out := []string{m.header(W, ox, oy), ""}
		out = append(out, m.card(W, ox, oy+len(out))...)
		out = append(out, "")
		if m.searching {
			out = append(out, m.chips(ox, oy+len(out)), "")
		}
		listH, y := H-len(out)-2, oy+len(out)
		if W >= 90 {
			sideW := min(48, W*2/5)
			listW := W - sideW - 2
			list := strings.Join(fit(m.list(listW, listH, ox, y), listH), "\n")
			side := panel.Width(sideW).Height(listH).MaxHeight(listH).Render(strings.Join(m.side(sideW, ox+listW+2, y), "\n"))
			out = append(out, strings.Split(lipgloss.JoinHorizontal(lipgloss.Top, lipgloss.NewStyle().Width(listW).Render(list), "  ", side), "\n")...)
		} else {
			out = append(out, fit(m.list(W, listH, ox, y), listH)...)
		}
		content = strings.Join(append(fit(out, H-1), m.footer(W)), "\n")
	}
	v.SetContent(lipgloss.NewStyle().MarginTop(oy).MarginLeft(ox).Render(content))
	return v
}
