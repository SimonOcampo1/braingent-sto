package ui

import "testing"

func TestHitsFindsTheTargetUnderTheClick(t *testing.T) {
	var h hits
	h.add(10, 0, 7, target{"tab", 2})
	h.add(0, 5, 40, target{"row", 9})
	if got, ok := h.at(12, 0); !ok || got != (target{"tab", 2}) {
		t.Fatalf("at(12,0) = %v %v", got, ok)
	}
	if _, ok := h.at(17, 0); ok {
		t.Fatal("x0+w is past the target")
	}
	if got, _ := h.at(39, 5); got != (target{"row", 9}) {
		t.Fatalf("at(39,5) = %v", got)
	}
	h.reset()
	if _, ok := h.at(12, 0); ok {
		t.Fatal("reset forgets every target")
	}
}

func TestArrowsNameOnlyTheSidesThatMove(t *testing.T) {
	for _, c := range []struct {
		down, up int
		want     string
	}{{51, 2, "↓51 ↑2"}, {0, 3, "↑3"}, {4, 0, "↓4"}, {0, 0, ""}} {
		if got := arrows(c.down, c.up); got != c.want {
			t.Errorf("arrows(%d, %d) = %q, want %q", c.down, c.up, got, c.want)
		}
	}
}
