# Linewatch

AI code review that runs in your git hooks and puts its findings as comments on the lines in your IDE.

> **Status:** early development. The PyPI release is still the 0.0.1 placeholder; install from source to try the MVP.

## What it does

- `linewatch init` detects the LLMs available on your machine (Ollama, Bionic/LM Studio, Anthropic, OpenAI, Gemini and Azure OpenAI keys, the Claude Code CLI), lets you choose one, and installs the hooks.
- Runs on pre-commit, pre-push, or both, with native git hooks, Husky or the pre-commit framework.
- Runs gitleaks first, so secrets are caught before anything is sent to a model.
- Reviews only the lines you changed, for security and quality, and blocks at the severity your team sets.
- Never blocks because the model is down: a timeout or a bad answer lets the commit through.
- Writes findings to `.linewatch/last.sarif`, which the VS Code extension shows on the lines.

## Install

Requires Python 3.10 or later. For secret scanning, also install [gitleaks](https://github.com/gitleaks/gitleaks).

```
pipx install linewatch-cli
cd your-repo
linewatch init
```

## Commands

| Command | What it does |
|---|---|
| `linewatch init` | Setup wizard: model, hook, blocking levels |
| `linewatch init --yes` | Setup without questions, for joining a repo that is already configured |
| `linewatch model` | Switch to another model |
| `linewatch review` | Review the uncommitted changes by hand; `--range A..B` reviews commits |

Bypass a hook once with `git commit --no-verify` or `git push --no-verify`. Silence a single finding with a `linewatch:ignore` comment on its line.

## Settings

`.linewatch.yaml` is committed and holds the team rules:

```yaml
hook: pre-push            # pre-commit | pre-push | both
scope: changed-lines      # changed-lines | changed-files
categories:
  security:
    block_at: critical    # critical | warning | info | never
  quality:
    block_at: never
  style: off
exclude:
  - "*.lock"
  - "dist/**"
max_diff_lines: 2000
```

Each dev's model choice lives in `~/.config/linewatch/config.yaml`, which can also override `hook`.

## Repository layout

| Path | Package |
|---|---|
| `src/linewatch/` | Core CLI (PyPI `linewatch-cli`) |
| `npm/` | Thin wrapper for JS teams (npm `linewatch`) |
| `vscode/` | VS Code extension that shows findings on the lines |

## Licence

MIT
