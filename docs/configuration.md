# Configuration

Linewatch has two config files: the team rules in the repo, and each dev's own settings.

## Team rules: `.linewatch.yaml`

Committed to the repo. `linewatch init` writes it.

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

| Setting | What it does |
|---|---|
| `hook` | When Linewatch runs. A dev can override it in their user config. |
| `scope` | `changed-lines` reports findings only on the lines you changed; the model still sees the code around them. `changed-files` reports findings anywhere in a file you touched. |
| `categories` | The lowest severity that blocks, for each category. `never` shows findings without blocking; `off` turns the category off. |
| `exclude` | Files that are never reviewed, as glob patterns. |
| `max_diff_lines` | Above this size, only gitleaks runs, and Linewatch says so. |

### Categories and severities

- **security** reports critical, warning and info findings.
- **quality** reports warning and info findings.
- `block_at: warning` blocks on warning and critical; `block_at: info` blocks on everything.

### Files that are always skipped

Besides `exclude`, Linewatch never reviews binaries, lockfiles (`package-lock.json`, `yarn.lock`, `poetry.lock`, `uv.lock`, `Cargo.lock`, `go.sum` and others), minified files and source maps, protobuf output, and files marked as generated (`@generated`, `do not edit`, `auto-generated`).

## Your settings: `~/.config/linewatch/config.yaml`

Stays out of the repo. `linewatch init` and `linewatch model` write it.

```yaml
provider: claude-code
command: /opt/homebrew/bin/claude
model: claude-opus-5-5   # optional for CLIs
hook: pre-commit         # optional: overrides the team's hook
```

It applies to all your repos, including the `hook` override. It follows `XDG_CONFIG_HOME` if you set it.

## Hooks

Linewatch installs into whatever the repo already uses:

| Repo uses | Linewatch adds |
|---|---|
| Nothing | Native git hooks in `.git/hooks` |
| [Husky](https://typicode.github.io/husky/) (`.husky/`) | A line in the Husky hook files; commit them |
| [pre-commit](https://pre-commit.com) (`.pre-commit-config.yaml`) | Local hooks in that file; commit it |

Both the pre-commit and pre-push hooks are always installed. Each run checks the team's `hook` and your override, and exits at once if it isn't the active one, so changing `hook` takes effect without reinstalling.

Commits from a GUI, such as the VS Code Source Control view, run the hooks too. Linewatch asks nothing there: a block shows up as the git client's error, and the findings appear in the editor.

## Files Linewatch writes in the repo

| Path | What it is |
|---|---|
| `.linewatch/last.sarif` | The findings of the last review, in SARIF, for the editor |
| `.linewatch/.gitignore` | Keeps `last.sarif` out of git; written on the first review |
