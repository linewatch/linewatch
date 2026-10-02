import json

from linewatch import output
from linewatch.findings import Finding

F1 = Finding("src/app.py", 42, "critical", "security", "SQL injection", "Use a parameterized query.")
F2 = Finding("src/app.py", 50, "info", "quality", "Unused variable")


def test_terminal_lines():
    assert output.terminal_lines([F1, F2], [F1]) == [
        "src/app.py:42:1: critical: [security] SQL injection (blocks)",
        "    fix: Use a parameterized query.",
        "src/app.py:50:1: info: [quality] Unused variable",
    ]


def test_sarif_shape():
    data = output.sarif([F1, F2])
    assert data["version"] == "2.1.0"
    run = data["runs"][0]
    assert run["tool"]["driver"]["name"] == "linewatch"
    first = run["results"][0]
    assert first["level"] == "error"
    assert first["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "src/app.py"
    assert first["locations"][0]["physicalLocation"]["region"]["startLine"] == 42
    assert first["properties"]["severity"] == "critical"
    assert run["results"][1]["level"] == "note"


def test_write_sarif_and_gitignore(tmp_path):
    path = output.write_sarif(tmp_path, [F1])
    assert json.loads(path.read_text())["runs"][0]["results"][0]["ruleId"] == "security"
    assert (tmp_path / ".linewatch" / ".gitignore").read_text() == "last.sarif\n"
    output.write_sarif(tmp_path, [])
    assert json.loads(path.read_text())["runs"][0]["results"] == []
    assert (tmp_path / ".linewatch" / ".gitignore").read_text() == "last.sarif\n"


def test_write_sarif_keeps_existing_gitignore(tmp_path):
    (tmp_path / ".linewatch").mkdir()
    (tmp_path / ".linewatch" / ".gitignore").write_text("cache/\n")
    output.write_sarif(tmp_path, [])
    assert (tmp_path / ".linewatch" / ".gitignore").read_text() == "cache/\nlast.sarif\n"
