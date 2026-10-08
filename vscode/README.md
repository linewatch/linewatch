# Linewatch for VS Code

Shows the findings of [Linewatch](https://github.com/linewatch/linewatch) on the lines in your editor. Linewatch is an AI code review that runs in your git hooks: it reviews the lines you changed for security and quality problems, with the model you already use (Claude Code, Codex, Antigravity or a local model), and blocks a commit or push when it finds something serious.

![Findings shown as markers in the editor](https://raw.githubusercontent.com/linewatch/linewatch/main/docs/images/vscode-markers.png)

## Features

- **Findings on the lines**, like linter warnings: critical as an error, warning as a warning, info as a hint. Hover a marker for the message and the suggested fix.
- **Problems panel**: all findings of the last review, with their file and line.
- **Live updates**: the markers change as soon as a review finishes, from a hook or `linewatch review`. A review with no findings clears them.
- **Commits from the Source Control view** run the hooks too. When a finding blocks, VS Code shows the git error and the markers appear at the same time.

![Findings in the Problems panel](https://raw.githubusercontent.com/linewatch/linewatch/main/docs/images/vscode-problems.png)

<img src="https://raw.githubusercontent.com/linewatch/linewatch/main/docs/images/vscode-blocked-commit.png" alt="A commit from VS Code blocked by Linewatch" width="290">

## Requirements

This extension shows what the Linewatch CLI writes; it doesn't review code itself. Set up the CLI in your repo first:

```
pipx install linewatch-cli
cd your-repo
linewatch init
```

With uv, use `uv tool install linewatch-cli` instead. See [Getting started](https://github.com/linewatch/linewatch/blob/main/docs/getting-started.md).

The extension starts in any workspace folder that has `.linewatch.yaml` or `.linewatch/last.sarif`.

## Commands

| Command | What it does |
|---|---|
| `Linewatch: Show Status` | Shows how many findings the last review left |
| `Linewatch: Reload Findings` | Reads `.linewatch/last.sarif` again |

## More

- [Documentation](https://github.com/linewatch/linewatch#docs)
- [Report a problem](https://github.com/linewatch/linewatch/issues)
