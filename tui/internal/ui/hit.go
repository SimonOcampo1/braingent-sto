package ui

import "fmt"

// target is what a click lands on: a tab, a list row, a button.
type target struct {
	kind string
	i    int
}

type hit struct {
	x, y, w int
	t       target
}

// hits maps screen cells to targets. View rebuilds it every frame, so a
// click always reads the layout the user is looking at.
type hits []hit

func (h *hits) add(x, y, w int, t target) { *h = append(*h, hit{x, y, w, t}) }

func (h *hits) reset() { *h = (*h)[:0] }

func (h hits) at(x, y int) (target, bool) {
	for _, r := range h {
		if y == r.y && x >= r.x && x < r.x+r.w {
			return r.t, true
		}
	}
	return target{}, false
}

// arrows is the header's pending count: "↓51 ↑2", only the sides that move.
func arrows(down, up int) string {
	switch {
	case down > 0 && up > 0:
		return fmt.Sprintf("↓%d ↑%d", down, up)
	case down > 0:
		return fmt.Sprintf("↓%d", down)
	case up > 0:
		return fmt.Sprintf("↑%d", up)
	}
	return ""
}
