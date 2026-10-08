# linewatch

AI code review that runs in your git hooks and puts its findings on the lines in your IDE.

This package lets JavaScript teams run [Linewatch](https://github.com/linewatch/linewatch) with `npx` and Husky. Linewatch itself is a Python CLI (PyPI [`linewatch-cli`](https://pypi.org/project/linewatch-cli/)); this package runs it for you.

```
npx linewatch init
```

## How it finds the CLI

1. If `linewatch` from PyPI is installed, it runs that.
2. If not, and you're in a terminal, it offers to install it with `uv tool install linewatch-cli` or `pipx install linewatch-cli`, then runs it. A lasting install is best: the git hooks need it later.
3. Otherwise, for example in a hook, it runs the CLI once with `uvx` or `pipx run`.
4. If none of these are available, it explains how to install the CLI. A hook then skips the review instead of blocking.

Linewatch needs Python 3.10 or later. With Husky, `linewatch init` adds its hook lines to `.husky/`; commit them.

## Docs

- [Getting started](https://github.com/linewatch/linewatch/blob/main/docs/getting-started.md)
- [Models](https://github.com/linewatch/linewatch/blob/main/docs/models.md)
- [Configuration](https://github.com/linewatch/linewatch/blob/main/docs/configuration.md)

MIT licence.
