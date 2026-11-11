package ui

import (
	"fmt"
	"sort"

	"github.com/SimonOcampo1/braingent-sto/tui/internal/sto"
)

// item is one row of any tab, flattened so the list, the sidebar and the
// search results treat chats, memories, tools and settings alike.
type item struct {
	kind  string // chat, memory, skill, plugin, setting, note
	id    string // what `sto data detail` / `sto act` take
	title string
	group string // what arrange groups by: the project, or Skills / Plugins
	sub   string // the second column: machine, memory type, current value
	mtime float64
	state string // both, local, repo, gone; "" when it has no sync state
	desc  string
	tab   int // where a search hit lives; -1 when it has no tab (a vault note)
	chat  *sto.Chat
}

// line is one row of a list: an item, a group title (group set, it nil) or
// the blank spacer between groups (both empty). Only items are selected.
type line struct {
	it    *item
	group string
	count int
	here  bool // the title of the project of the folder the TUI runs in
}

// arrange orders items newest first, keeping the given order among equal
// times; grouped, it puts each group under a title, the group with the
// newest item first, a spacer between groups.
func arrange(its []item, here string, grouped bool) []line {
	its = append([]item(nil), its...)
	latest, count, first := map[string]float64{}, map[string]int{}, map[string]int{}
	for i, it := range its {
		latest[it.group] = max(latest[it.group], it.mtime)
		count[it.group]++
		if _, ok := first[it.group]; !ok {
			first[it.group] = i
		}
	}
	sort.SliceStable(its, func(i, j int) bool {
		a, b := its[i], its[j]
		if grouped && a.group != b.group {
			if latest[a.group] != latest[b.group] {
				return latest[a.group] > latest[b.group]
			}
			return first[a.group] < first[b.group]
		}
		return a.mtime > b.mtime
	})
	var out []line
	for i := range its {
		g := its[i].group
		if grouped && (i == 0 || its[i-1].group != g) {
			if i > 0 {
				out = append(out, line{})
			}
			out = append(out, line{group: g, count: count[g], here: g == here})
		}
		out = append(out, line{it: &its[i]})
	}
	return out
}

// step moves from index i by dir to the next item, skipping titles and
// spacers; at either end it stays on i.
func step(ls []line, i, dir int) int {
	for j := i + dir; j >= 0 && j < len(ls); j += dir {
		if ls[j].it != nil {
			return j
		}
	}
	return i
}

func chatItems(d *sto.Chats) []item {
	var out []item
	for i := range d.Rows {
		c := &d.Rows[i]
		out = append(out, item{kind: "chat", id: c.ID, title: c.Title, group: c.Project,
			sub: c.Machine, mtime: c.Mtime, state: c.State, chat: c})
	}
	return out
}

func memoryItems(d *sto.Memories) []item {
	var out []item
	for _, p := range d.Projects {
		for _, m := range p.Memories {
			out = append(out, item{kind: "memory", id: p.Project + "/" + m.Machine + "/" + m.Slug,
				title: m.Slug, group: p.Project, sub: m.Type, mtime: m.Mtime, desc: m.Description})
		}
	}
	return out
}

func toolItems(d *sto.Tools, skills, plugins string) []item {
	var out []item
	for _, g := range []struct {
		name string
		rows []sto.Tool
	}{{skills, d.Skills}, {plugins, d.Plugins}} {
		for _, t := range g.rows {
			out = append(out, item{kind: t.What, id: t.ID, title: t.Label, group: g.name,
				state: t.Where, desc: t.Desc})
		}
	}
	return out
}

// hitItems turns search hits into items that know their tab and their id
// there, the current tab's hits first.
func hitItems(hits []sto.Hit, current int) []item {
	str := func(m map[string]any, k string) string { s, _ := m[k].(string); return s }
	var out []item
	for _, h := range hits {
		it := item{title: h.Label, sub: h.Sub, tab: -1, kind: h.Kind}
		switch h.Kind {
		case "session":
			it.kind, it.tab, it.id = "chat", tChats, str(h.Ref, "id")
		case "memory":
			it.tab, it.id = tMemories, fmt.Sprintf("%s/%s/%s", str(h.Ref, "project"), str(h.Ref, "machine"), str(h.Ref, "slug"))
		case "tool":
			it.kind, it.tab, it.id = str(h.Ref, "what"), tTools, str(h.Ref, "id")
		case "note":
			it.id = str(h.Ref, "path")
		}
		out = append(out, it)
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].tab == current && out[j].tab != current })
	return out
}
