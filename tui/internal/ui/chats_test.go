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
		case l.chat != nil:
			out = append(out, l.chat.Title)
		case l.project != "":
			out = append(out, fmt.Sprintf("title %s %d %v", l.project, l.count, l.here))
		default:
			out = append(out, "spacer")
		}
	}
	return out
}

func TestArrangeGroupsByProjectNewestFirst(t *testing.T) {
	rows := []sto.Chat{
		{Title: "old a", Project: "a", Mtime: 1},
		{Title: "new b", Project: "b", Mtime: 5},
		{Title: "mid a", Project: "a", Mtime: 3},
		{Title: "old b", Project: "b", Mtime: 2},
	}
	got := fmt.Sprint(describe(arrange(rows, "a", true)))
	want := fmt.Sprint([]string{"title b 2 false", "new b", "old b", "spacer", "title a 2 true", "mid a", "old a"})
	if got != want {
		t.Fatalf("grouped = %v\nwant      %v", got, want)
	}
	got = fmt.Sprint(describe(arrange(rows, "a", false)))
	if want := fmt.Sprint([]string{"new b", "mid a", "old b", "old a"}); got != want {
		t.Fatalf("flat = %v, want %v", got, want)
	}
}

func TestStepSkipsTitlesAndSpacers(t *testing.T) {
	ls := arrange([]sto.Chat{{Title: "x", Project: "a", Mtime: 2}, {Title: "y", Project: "b", Mtime: 1}}, "", true)
	// title a, x, spacer, title b, y
	if i := step(ls, 0, 1); i != 1 {
		t.Fatalf("first selectable = %d, want 1", i)
	}
	if i := step(ls, 1, 1); i != 4 {
		t.Fatalf("down from x = %d, want 4", i)
	}
	if i := step(ls, 4, 1); i != 4 {
		t.Fatalf("down from the last row stays, got %d", i)
	}
	if i := step(ls, 1, -1); i != 1 {
		t.Fatalf("up from the first row stays, got %d", i)
	}
}
