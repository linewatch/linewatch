# Linewatch

AI code review that runs in your git hooks and puts its findings as comments on the lines in your IDE.

> **Status:** early development. Version 0.0.1 is a placeholder release; the review engine is not implemented yet.

## What it will do

- `linewatch init` detects the LLMs available on your machine (local models, API keys, installed CLIs) and lets you choose one.
- Runs on pre-commit, pre-push, or both.
- Lets you set a blocking policy for each category, such as security, quality and style.
- Writes findings as SARIF so your IDE shows them on the lines.

## Install

```
pipx install linewatch-cli
linewatch --version
```

## Repository layout

| Path | Package |
|---|---|
| `src/linewatch/` | Core CLI (PyPI `linewatch-cli`) |
| `npm/` | Thin wrapper for JS teams (npm `linewatch`) |
| `vscode/` | VS Code extension that shows findings on the lines |

## Licence

MIT
