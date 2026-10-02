import json

import pytest
from conftest import fake_tool

from linewatch import gitleaks, llm, review
from linewatch.config import RepoConfig, UserConfig
from linewatch.diff import Changes, DiffLine, FileChange, Hunk

MODEL = UserConfig(provider="ollama", model="m", base_url="http://localhost:11434")

APP = "import os\nquery = 'SELECT * FROM t WHERE id=' + uid\nprint(query)  # linewatch:ignore\nx = 1\n"


def app_changes(extra_files=()):
    """app.py with line 1 unchanged and lines 2-4 added."""
    lines = APP.splitlines()
    hunk = Hunk([DiffLine(" ", 1, lines[0])] + [DiffLine("+", i, t) for i, t in enumerate(lines[1:], 2)])
    contents = {"app.py": APP}
    files = [FileChange("app.py", [hunk])]
    for path, text in extra_files:
        contents[path] = text
        files.append(FileChange(path, [Hunk([DiffLine("+", i, t) for i, t in enumerate(text.splitlines(), 1)])]))
    return Changes("test", files, contents.get)


def answer(*findings):
    def complete(user, system, prompt, schema):
        complete.calls.append((system, prompt, schema))
        return {"findings": list(findings)}
    complete.calls = []
    return complete


def item(line, severity="critical", category="security", file="app.py", message="SQL injection"):
    return {"file": file, "line": line, "severity": severity, "category": category,
            "message": message, "suggested_fix": "Use a parameterized query."}


@pytest.fixture(autouse=True)
def _no_gitleaks(no_gitleaks):
    pass


def test_blocking_finding():
    result = review.run(app_changes(), RepoConfig(), MODEL, answer(item(2)))
    (f,) = result.findings
    assert (f.file, f.line, f.severity, f.category) == ("app.py", 2, "critical", "security")
    assert result.blocking == [f]


def test_block_at_levels():
    found = answer(item(2, "warning"), item(4, "info", "quality", message="unused"))
    repo = RepoConfig(categories={"security": "critical", "quality": "info"})
    result = review.run(app_changes(), repo, MODEL, found)
    assert [f.line for f in result.blocking] == [4]


def test_findings_outside_scope_or_unknown_are_dropped():
    found = answer(
        item(1),                    # unchanged line
        item(99),                   # line doesn't exist
        item(2, file="other.py"),   # file not in the diff
        item(2, category="style"),  # category without a check
        item(2, severity="high"),   # unknown severity
        {"file": "app.py", "line": "two"},
        item(2, file="./app.py", message="kept"),
    )
    result = review.run(app_changes(), RepoConfig(), MODEL, found)
    assert [(f.file, f.message) for f in result.findings] == [("app.py", "kept")]


def test_changed_files_scope_allows_unchanged_lines():
    repo = RepoConfig(scope="changed-files")
    result = review.run(app_changes(), repo, MODEL, answer(item(1), item(99)))
    assert [f.line for f in result.findings] == [1]


def test_linewatch_ignore_suppresses():
    result = review.run(app_changes(), RepoConfig(), MODEL, answer(item(3)))
    assert result.findings == []


def test_quality_cannot_be_critical():
    result = review.run(app_changes(), RepoConfig(), MODEL, answer(item(4, "critical", "quality")))
    assert result.findings[0].severity == "warning"
    assert result.blocking == []  # quality blocks at `never` by default


def test_duplicates_are_merged():
    result = review.run(app_changes(), RepoConfig(), MODEL, answer(item(2), item(2)))
    assert len(result.findings) == 1


def test_off_category_is_not_asked_or_reported():
    complete = answer(item(2))
    repo = RepoConfig(categories={"security": "off", "quality": "never"})
    result = review.run(app_changes(), repo, MODEL, complete)
    system, _, schema = complete.calls[0]
    assert "Security:" not in system and "Quality:" in system
    assert schema["properties"]["findings"]["items"]["properties"]["category"]["enum"] == ["quality"]
    assert result.findings == []


def test_prompt_shows_line_numbers_and_markers():
    complete = answer()
    review.run(app_changes(), RepoConfig(), MODEL, complete)
    _, prompt, _ = complete.calls[0]
    assert "File: app.py" in prompt
    assert "     1   import os" in prompt
    assert "     2 + query = " in prompt


def test_model_failure_fails_open():
    def broken(*args):
        raise llm.ModelError("ollama: connection refused")
    result = review.run(app_changes(), RepoConfig(), MODEL, broken)
    assert result.findings == [] and result.blocking == []
    assert any("connection refused" in n for n in result.notes)


def test_deterministic_only_mode_skips_the_model():
    complete = answer(item(2))
    result = review.run(app_changes(), RepoConfig(), UserConfig(provider="none"), complete)
    assert complete.calls == [] and result.findings == []


def test_no_user_config_says_so():
    complete = answer(item(2))
    result = review.run(app_changes(), RepoConfig(), None, complete)
    assert complete.calls == []
    assert any("linewatch init" in n for n in result.notes)


def test_size_limit_skips_the_model():
    complete = answer(item(2))
    result = review.run(app_changes(), RepoConfig(max_diff_lines=2), MODEL, complete)
    assert complete.calls == []
    assert any("over the limit of 2" in n for n in result.notes)


def test_excluded_files_are_not_sent():
    complete = answer()
    changes = app_changes([("yarn.lock", "x\n"), ("dist/a.js", "y\n")])
    result = review.run(changes, RepoConfig(), MODEL, complete)
    assert all("yarn.lock" not in prompt and "dist/a.js" not in prompt for _, prompt, _ in complete.calls)
    assert any("yarn.lock" in n and "dist/a.js" in n for n in result.notes)


def test_large_changes_are_split_into_chunks():
    big = "\n".join(f"line{i}" for i in range(1, 951)) + "\n"
    complete = answer()
    review.run(app_changes([("big.py", big)]), RepoConfig(max_diff_lines=5000), MODEL, complete)
    prompts = [p for _, p, _ in complete.calls]
    assert len(prompts) == 3
    assert all(p.count("\n") <= review.MAX_CHUNK_LINES + 10 for p in prompts)
    assert "line950" in prompts[-1]


def test_one_failed_chunk_keeps_the_others():
    big = "\n".join(f"line{i}" for i in range(1, 501)) + "\n"

    def flaky(user, system, prompt, schema):
        if "line450" in prompt:
            raise llm.ModelError("timeout")
        return {"findings": [item(2)]}

    result = review.run(app_changes([("big.py", big)]), RepoConfig(), MODEL, flaky)
    assert len(result.findings) == 1
    assert any("1 of 2 part(s)" in n for n in result.notes)


# gitleaks

GITLEAKS_SCRIPT = """\
# Fake gitleaks: report a leak on line 2 of app.py; `dir` is unknown, like gitleaks < 8.19.
[ "$1" = "dir" ] && { echo "unknown command dir" >&2; exit 1; }
while [ $# -gt 0 ]; do
  case "$1" in --source) src="$2"; shift;; --report-path) report="$2"; shift;; esac
  shift
done
cat > "$report" <<EOF
[{"File": "$src/app.py", "StartLine": 2, "RuleID": "generic-api-key",
  "Description": "Generic API Key", "Secret": "hunter2", "Match": "key=hunter2"}]
EOF
"""


def test_gitleaks_finding_blocks_even_when_the_model_fails(tmp_path, monkeypatch):
    fake_tool(tmp_path / "bin", "gitleaks", GITLEAKS_SCRIPT)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:/usr/bin:/bin")
    monkeypatch.setattr(gitleaks, "available", lambda: True)

    def broken(*args):
        raise llm.ModelError("down")

    result = review.run(app_changes(), RepoConfig(), MODEL, broken)
    (f,) = result.findings
    assert (f.file, f.line, f.source, f.severity) == ("app.py", 2, "gitleaks", "critical")
    assert "hunter2" not in f.message
    assert result.blocking == [f]


def test_missing_gitleaks_is_reported():
    result = review.run(app_changes(), RepoConfig(), MODEL, answer())
    assert any("gitleaks is not installed" in n for n in result.notes)
