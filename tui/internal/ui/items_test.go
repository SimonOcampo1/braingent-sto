package ui

import (
	"fmt"
	"testing"

	"github.com/SimonOcampo1/braingent-sto/tui/internal/sto"
)

func describe(ls []line) []string {
	var out []string
	for _, l := range ls {
		switch {
		case l.it != nil:
			out = append(out, l.it.title)
		case l.group != "":
			out = append(out, fmt.Sprintf("title %s %d %v", l.group, l.count, l.here))
			if l.folded {
				out[len(out)-1] += " folded"
			}
		default:
			out = append(out, "spacer")
		}
	}
	return out
}

func TestArrangeGroupsNewestFirst(t *testing.T) {
	its := []item{
		{title: "old a", group: "a", mtime: 1},
		{title: "new b", group: "b", mtime: 5},
		{title: "mid a", group: "a", mtime: 3},
		{title: "old b", group: "b", mtime: 2},
	}
	got := fmt.Sprint(describe(arrange(its, "a", true, nil)))
	want := fmt.Sprint([]string{"title b 2 false", "new b", "old b", "spacer", "title a 2 true", "mid a", "old a"})
	if got != want {
		t.Fatalf("grouped = %v\nwant      %v", got, want)
	}
	got = fmt.Sprint(describe(arrange(its, "a", false, nil)))
	if want := fmt.Sprint([]string{"new b", "mid a", "old b", "old a"}); got != want {
		t.Fatalf("flat = %v, want %v", got, want)
	}
}

func TestArrangeKeepsTheGivenOrderWhenNothingHasATime(t *testing.T) {
	its := []item{{title: "x", group: "Skills"}, {title: "y", group: "Skills"}, {title: "p", group: "Plugins"}}
	got := fmt.Sprint(describe(arrange(its, "", true, nil)))
	if want := fmt.Sprint([]string{"title Skills 2 false", "x", "y", "spacer", "title Plugins 1 false", "p"}); got != want {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestStepStopsOnItemsAndTitlesButNotSpacers(t *testing.T) {
	ls := arrange([]item{{title: "x", group: "a", mtime: 2}, {title: "y", group: "b", mtime: 1}}, "", true, nil)
	// title a, x, spacer, title b, y
	for _, c := range []struct{ from, dir, want int }{{-1, 1, 0}, {1, 1, 3}, {4, 1, 4}, {3, -1, 1}, {0, -1, 0}} {
		if got := step(ls, c.from, c.dir); got != c.want {
			t.Errorf("step(%d, %d) = %d, want %d", c.from, c.dir, got, c.want)
		}
	}
}

func TestAFoldedGroupKeepsItsTitleAndHidesItsItems(t *testing.T) {
	its := []item{{title: "x", group: "a", mtime: 2}, {title: "y", group: "b", mtime: 1}}
	got := fmt.Sprint(describe(arrange(its, "", true, map[string]bool{"a": true})))
	if want := fmt.Sprint([]string{"title a 1 false folded", "title b 1 false", "y"}); got != want {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestMemoryItemsAreFiledByProjectWithAPathID(t *testing.T) {
	var d sto.Memories
	d.Projects = append(d.Projects, sto.MemoryProject{Project: "p", Memories: []sto.Memory{{Slug: "s", Machine: "pc", Type: "project"}}})
	its := memoryItems(&d)
	if len(its) != 1 || its[0].id != "p/pc/s" || its[0].group != "p" || its[0].kind != "memory" {
		t.Fatalf("memory items = %+v", its)
	}
}

func TestHitsPointAtTheirTabAndCurrentTabComesFirst(t *testing.T) {
	hits := []sto.Hit{
		{Kind: "session", Label: "chat", Ref: map[string]any{"id": "c1"}},
		{Kind: "memory", Label: "mem", Ref: map[string]any{"project": "p", "machine": "pc", "slug": "s"}},
		{Kind: "tool", Label: "tool", Ref: map[string]any{"id": "personal:x", "what": "skill"}},
		{Kind: "note", Label: "note", Ref: map[string]any{"path": "/v/n.md"}},
	}
	its := hitItems(hits, tMemories)
	got := ""
	for _, it := range its {
		got += fmt.Sprintf("%s:%s:%d ", it.title, it.id, it.tab)
	}
	if want := "mem:p/pc/s:1 chat:c1:0 tool:personal:x:2 note:/v/n.md:-1 "; got != want {
		t.Fatalf("got  %q\nwant %q", got, want)
	}
}
