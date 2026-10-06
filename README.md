# Linewatch

AI code review that runs in your git hooks and puts its findings on the lines in your IDE.

> **Status:** early development. PyPI and the VS Code Marketplace still have 0.0.1 placeholders; until 0.1.0, install from a clone (see [Getting started](docs/getting-started.md)).

![A push blocked by Linewatch|686](docs/images/blocked-push.svg)

## What it does

- **Uses the model you already have.** `linewatch init` finds the coding CLIs (Claude Code, Codex, Antigravity) and local models (Bionic/LM Studio) on your machine and lets you pick one. No API key needed.
- **Runs in your hooks**, on push, on commit or both, with native git hooks, Husky or the pre-commit framework.
- **Catches secrets first** with gitleaks, before anything is sent to a model.
- **Reviews only the lines you changed**, for security and quality, and blocks at the severity your team sets.
- **Never blocks because the model is down.** A timeout or a bad answer lets the commit through; gitleaks findings still count.
- **Shows findings in VS Code** as markers on the lines, from `.linewatch/last.sarif`.

## Quick start

Requires Python 3.10 or later. Install [gitleaks](https://github.com/gitleaks/gitleaks) too, for secret scanning.

```
pipx install linewatch-cli
cd your-repo
linewatch init
```

![The linewatch init wizard|690](docs/images/wizard.svg)

Commit the `.linewatch.yaml` it writes. Teammates then run `linewatch init --yes`.

![Findings shown as markers in VS Code](docs/images/vscode-markers.png)

## Models

| Model | Status | One review |
|---|---|---|
| Claude Code CLI | Tested | about 7 s |
| Codex CLI | Tested | about 6 s |
| Antigravity CLI | Tested | about 30–60 s |
| Bionic (LM Studio): Qwen 3.8 27B, Gemma 4 31B | Tested | about 8 s / 22–40 s |
| No model: gitleaks only | Tested | under 1 s |
| Anthropic, OpenAI, Gemini, Azure OpenAI APIs, Ollama | Untested | |

Each tested model blocked all 12 problem cases in our test suite (leaked secrets, SQL injection, command injection, path traversal, XSS, unsafe deserialization, SSRF, JWT auth bypass) on commit and on push. See [Models](docs/models.md).

## Commands

| Command | What it does |
|---|---|
| `linewatch init` | Setup wizard: model, hook, blocking levels |
| `linewatch init --yes` | Setup without questions, for joining a repo that is already configured |
| `linewatch model` | Switch to another model |
| `linewatch review` | Review the uncommitted changes by hand; `--range A..B` reviews commits |

Bypass a hook once with `git commit --no-verify` or `git push --no-verify`. Silence a single finding with a `linewatch:ignore` comment on its line.

## Docs

- [Getting started](docs/getting-started.md): install, set up a repo, what happens on a push
- [Models](docs/models.md): the models Linewatch can use and how to set each up
- [Configuration](docs/configuration.md): `.linewatch.yaml`, your user config, hooks
- [VS Code extension](docs/vscode.md): markers, the Problems panel, commits from the Source Control view

## Repository layout

| Path | Package |
|---|---|
| `src/linewatch/` | Core CLI (PyPI `linewatch-cli`) |
| `npm/` | Thin wrapper for JS teams (npm `linewatch`) |
| `vscode/` | VS Code extension that shows findings on the lines |
| `docs/` | Documentation |

## Licence

MIT
