package ui

import (
	"strconv"

	"charm.land/lipgloss/v2"
)

// Only ANSI colors, so the TUI inherits the terminal's palette. The accent
// is the one `sto ui` saved; setAccent repaints every style that uses it.
var (
	muted                                   = lipgloss.Color("8")
	ink                                     = lipgloss.Color("0")
	faint                                   = lipgloss.NewStyle().Foreground(muted)
	bold                                    = lipgloss.NewStyle().Bold(true)
	errStyle                                = lipgloss.NewStyle().Foreground(lipgloss.Color("1"))
	panel                                   = lipgloss.NewStyle().Border(lipgloss.RoundedBorder()).BorderForeground(muted).Padding(0, 1)
	tabIdle                                 = lipgloss.NewStyle().Foreground(muted).Padding(0, 1)
	brand, acc, tabActive, button, sel, grp lipgloss.Style
	popup                                   lipgloss.Style
)

func init() { setAccent("36") }

// setAccent takes the SGR foreground code the engine sends ("36" is cyan).
func setAccent(code string) {
	n, err := strconv.Atoi(code)
	if err != nil || n < 30 || n > 37 {
		n = 36
	}
	a := lipgloss.Color(strconv.Itoa(n - 30))
	brand = lipgloss.NewStyle().Bold(true).Foreground(a).Padding(0, 1)
	acc = lipgloss.NewStyle().Foreground(a)
	grp = lipgloss.NewStyle().Bold(true).Foreground(a)
	tabActive = lipgloss.NewStyle().Bold(true).Foreground(ink).Background(a).Padding(0, 1)
	button = tabActive
	sel = lipgloss.NewStyle().Foreground(ink).Background(a)
	popup = lipgloss.NewStyle().Border(lipgloss.RoundedBorder()).BorderForeground(a).Padding(1, 2)
}
