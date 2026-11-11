package ui

import (
	"sort"

	"github.com/SimonOcampo1/braingent-sto/tui/internal/sto"
)

// line is one row of a list: a chat, a group title (project set, chat nil)
// or the blank spacer between groups (both empty). Only chats are selected.
type line struct {
	chat    *sto.Chat
	project string
	count   int
	here    bool // the title of the project of the folder the TUI runs in
}

// arrange orders rows newest first; grouped, it puts each project under a
// title, the project with the newest chat first, a spacer between groups.
func arrange(rows []sto.Chat, here string, grouped bool) []line {
	rows = append([]sto.Chat(nil), rows...)
	latest, count := map[string]float64{}, map[string]int{}
	for _, r := range rows {
		latest[r.Project] = max(latest[r.Project], r.Mtime)
		count[r.Project]++
	}
	sort.SliceStable(rows, func(i, j int) bool {
		a, b := rows[i], rows[j]
		if grouped && a.Project != b.Project {
			if latest[a.Project] != latest[b.Project] {
				return latest[a.Project] > latest[b.Project]
			}
			return a.Project < b.Project
		}
		return a.Mtime > b.Mtime
	})
	var out []line
	for i := range rows {
		p := rows[i].Project
		if grouped && (i == 0 || rows[i-1].Project != p) {
			if i > 0 {
				out = append(out, line{})
			}
			out = append(out, line{project: p, count: count[p], here: p == here})
		}
		out = append(out, line{chat: &rows[i]})
	}
	return out
}

// step moves from index i by dir to the next chat, skipping titles and
// spacers; at either end it stays on i.
func step(ls []line, i, dir int) int {
	for j := i + dir; j >= 0 && j < len(ls); j += dir {
		if ls[j].chat != nil {
			return j
		}
	}
	return i
}
