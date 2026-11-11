package sto

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// fake writes a stand-in for `sto` that prints body and exits with code.
func fake(t *testing.T, body string, code int) Client {
	t.Helper()
	bin := filepath.Join(t.TempDir(), "sto")
	script := "#!/bin/sh\ncat <<'END'\n" + body + "\nEND\nexit " + string(rune('0'+code)) + "\n"
	if err := os.WriteFile(bin, []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	return Client{Bin: bin}
}

func TestDataDecodesTheView(t *testing.T) {
	var s Status
	err := fake(t, `{"state": "pending", "down": 2, "up": 1, "project": null,
		"parts": {"down": ["2 memories"], "up": []}, "labels": {"act_sync": "Sync"}}`, 0).Data(&s, "status")
	if err != nil {
		t.Fatal(err)
	}
	if s.State != "pending" || s.Down != 2 || s.Project != "" || s.L("act_sync") != "Sync" {
		t.Fatalf("status = %+v", s)
	}
	if s.L("missing") != "missing" {
		t.Fatalf("a missing label falls back to its key, got %q", s.L("missing"))
	}
}

func TestDataTurnsTheEngineErrorIntoAGoError(t *testing.T) {
	var s Status
	if err := fake(t, `{"error": "ZeroDivisionError: boom"}`, 0).Data(&s, "status"); err == nil || err.Error() != "ZeroDivisionError: boom" {
		t.Fatalf("err = %v", err)
	}
	if err := fake(t, ``, 1).Data(&s, "status"); err == nil {
		t.Fatal("a failing sto must be an error")
	}
}

func TestActStreamsStepsAndReturnsTheFinalLine(t *testing.T) {
	c := fake(t, `{"step": "bringing"}
{"step": "sending"}
{"done": true, "message": "synced"}`, 0)
	var steps []string
	msg, err := c.Act(func(s string) { steps = append(steps, s) }, "sync", "--all")
	if err != nil || msg != "synced" || len(steps) != 2 || steps[1] != "sending" {
		t.Fatalf("msg = %q, err = %v, steps = %v", msg, err, steps)
	}
	_, err = fake(t, `{"step": "bringing"}
{"error": "no connection"}`, 0).Act(func(string) {}, "sync")
	if err == nil || err.Error() != "no connection" {
		t.Fatalf("err = %v", err)
	}
}

func TestDataCtxKillsTheEngineWhenCancelled(t *testing.T) {
	bin := filepath.Join(t.TempDir(), "sto")
	os.WriteFile(bin, []byte("#!/bin/sh\nexec sleep 5\n"), 0o755)
	ctx, cancel := context.WithCancel(context.Background())
	start := time.Now()
	go func() { time.Sleep(50 * time.Millisecond); cancel() }()
	var s Search
	if err := (Client{Bin: bin}).DataCtx(ctx, &s, "search"); err == nil || time.Since(start) > 2*time.Second {
		t.Fatalf("err = %v after %v", err, time.Since(start))
	}
}
