import json
import os
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path
from dream_extract import (
    parse_lines, build_distilled, read_marker, ran_today, mark_done, find_sessions,
)


def test_parse_lines():
    lines = [
        json.dumps({"type": "user", "message": {"role": "user", "content": "Fix the auth bug"}}),
        json.dumps({"type": "user", "message": {"role": "user", "content": "<local-command-caveat>noise</x>"}}),
        json.dumps({"type": "assistant", "message": {"role": "assistant",
            "content": [{"type": "tool_use", "name": "Edit"}, {"type": "text", "text": "ok"}]}}),
        json.dumps({"type": "user", "message": {"role": "user",
            "content": [{"type": "tool_result", "is_error": True, "content": "boom"}]}}),
        "{not valid json",
    ]
    r = parse_lines(lines)
    assert r["prompts"] == ["Fix the auth bug"], r["prompts"]
    assert r["tools"]["Edit"] == 1, r["tools"]
    assert r["errors"] == 1, r["errors"]


def test_build_distilled_caps():
    big = {"prompts": ["x" * 300 for _ in range(5)], "tools": Counter({"Bash": 3}), "errors": 0}
    sessions = [("projA", big), ("projB", big), ("projC", big)]
    out = build_distilled(sessions, max_chars=500)
    assert "truncated" in out, out
    assert len(out) < 900, len(out)  # cap + marker, not all three full sections
    assert out.startswith("## projA"), out[:20]


def test_marker_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        m = Path(d) / "last_run"
        assert read_marker(m) is None
        assert ran_today(m, date(2026, 6, 27)) is False
        mark_done(m, date(2026, 6, 27))
        assert read_marker(m) == date(2026, 6, 27)
        assert ran_today(m, date(2026, 6, 27)) is True
        assert ran_today(m, date(2026, 6, 28)) is False


def test_redaction():
    # shaped like the real thing, deliberately fake: a plausible-looking key in
    # a public repo trips secret scanners for nothing
    secrets = [
        "sk-or-v1-EXAMPLEEXAMPLEEXAMPLEEXAMPLEEXAMPLEEXAMPLEEXAMPLEEXAMPLE0000",
        "AQ.EXAMPLEEXAMPLEEXAMPLEEXAMPLEEXAMPLE0000",
        "AIzaEXAMPLEEXAMPLEEXAMPLEEXAMPLEEXAMPLE00",
        "ghp_EXAMPLEEXAMPLEEXAMPLEEXAMPLE000000",
    ]
    for sec in secrets:
        line = json.dumps({"type": "user", "message": {"role": "user", "content": f"my key is {sec} ok"}})
        r = parse_lines([line])
        assert sec not in r["prompts"][0], r["prompts"][0]
        assert "[REDACTED]" in r["prompts"][0], r["prompts"][0]


def test_find_sessions_date_filter():
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d) / "projX"
        proj.mkdir()
        old = proj / "old.jsonl"
        old.write_text("{}\n", encoding="utf-8")
        new = proj / "new.jsonl"
        new.write_text("{}\n", encoding="utf-8")
        os.utime(old, (1000, 1000))   # force old mtime far in the past
        found = find_sessions(2000, projects_dir=Path(d))  # cutoff between old and now
        names = [p.name for _, p in found]
        assert "new.jsonl" in names, names
        assert "old.jsonl" not in names, names
        assert found[0][0] == "projX", found


if __name__ == "__main__":
    test_parse_lines()
    test_build_distilled_caps()
    test_marker_roundtrip()
    test_redaction()
    test_find_sessions_date_filter()
    print("OK")
