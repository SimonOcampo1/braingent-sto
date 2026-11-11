// braingent's TUI. It reads and acts only through `sto data` / `sto act`.
package main

import (
	"fmt"
	"os"

	tea "charm.land/bubbletea/v2"

	"github.com/SimonOcampo1/braingent-sto/tui/internal/sto"
	"github.com/SimonOcampo1/braingent-sto/tui/internal/ui"
)

func main() {
	bin := os.Getenv("STO_BIN") // `sto ui` points it at itself
	if bin == "" {
		bin = "sto"
	}
	cwd, _ := os.Getwd()
	if _, err := tea.NewProgram(ui.New(sto.Client{Bin: bin}, cwd)).Run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
