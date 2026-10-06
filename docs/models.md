# Models

`linewatch init` and `linewatch model` look for these on your machine and list the ones they find.

## Tested

These were tested end to end: each one blocked all 12 problem cases (5 kinds of leaked secret and 7 code problems such as SQL injection and SSRF) on commit and on push, and let the 3 clean controls through.

| Model | How Linewatch finds it | One review | Good for |
|---|---|---|---|
| Claude Code CLI | `claude` on your PATH | about 7 s | pre-commit or pre-push |
| Codex CLI | `codex` on your PATH | about 6 s | pre-commit or pre-push |
| Antigravity CLI | `agy` on your PATH | about 30–60 s | pre-push |
| Bionic (LM Studio), Qwen 3.8 27B | local server on port 1234, or the `lms` CLI | about 8 s | pre-commit or pre-push |
| Bionic (LM Studio), Gemma 4 31B | local server on port 1234, or the `lms` CLI | about 22–40 s | pre-push |
| No model (gitleaks only) | always available | under 1 s | secrets only |

### Coding CLIs: Claude Code, Codex, Antigravity

If you already use one of these, Linewatch can use it with the login you have: no API key needed. Make sure it works on its own first:

```
claude --version     # Claude Code
codex login status   # Codex
agy models           # Antigravity
```

The wizard asks for a model name; leave it empty to use the CLI's default, or name one, such as `claude-opus-5-5` for Claude Code or `gemini-3.8-flash-medium` for Antigravity (`agy models` lists them).

Linewatch runs each CLI without tools, in an empty temporary folder, and sends only the diff in the prompt:

- **Claude Code** runs with tools, settings, hooks and MCP servers turned off.
- **Codex** runs read-only, without your Codex config, rules or session history.
- **Antigravity** runs in its sandbox. It has no option to turn tools off, so the prompt tells it it has none; if it still tries one and gives no answer, Linewatch asks once more.

### Bionic (LM Studio)

Bionic is the new name of LM Studio on macOS. Load a model in the app; Linewatch lists the chat models it has.

If the Bionic server is stopped, Linewatch still finds your models through the `lms` CLI in `~/.lmstudio/bin` and offers to start the server. The first review after a start is slower while the model loads.

Local models keep your code on your machine, which matters for company code.

### No model

Without a model, Linewatch runs gitleaks only: leaked secrets still block, but code problems such as SQL injection are not found. Run `linewatch model` once a model is available.

## Untested

These are supported in the code but not yet tested against the real services. The wizard shows them with `(untested)` after their names. Reports are welcome.

| Model | How Linewatch finds it |
|---|---|
| Anthropic API | `ANTHROPIC_API_KEY` |
| OpenAI API | `OPENAI_API_KEY` |
| Gemini API | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| Azure OpenAI | `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT` |
| Ollama | local server on port 11434 |

For an API, Linewatch stores the name of the environment variable, not the key. If you type a key into the wizard instead, it goes into your user config, which only you can read.

## Choosing

- **Speed:** a review runs on every commit or push. Models that answer in under 10 s work well on pre-commit; slower ones belong on pre-push.
- **Privacy:** for company code, use a local model or a provider your employer has approved.
- **Per dev:** the model is each dev's own choice. The team only shares the rules in `.linewatch.yaml`.
