// braingent's TUI. It reads and acts only through `braingent data` / `braingent act`.
package main

import (
	"fmt"
	"os"

	tea "charm.land/bubbletea/v2"

	"github.com/SimonOcampo1/braingent-sto/tui/internal/sto"
	"github.com/SimonOcampo1/braingent-sto/tui/internal/ui"
)

func main() {
	bin := os.Getenv("STO_BIN") // set it to try another build of the CLI
	if bin == "" {
		bin = "braingent"
	}
	cwd, _ := os.Getwd()
	if _, err := tea.NewProgram(ui.New(sto.Client{Bin: bin}, cwd)).Run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
