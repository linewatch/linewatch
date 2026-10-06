# Linewatch for VS Code

Shows the findings of [Linewatch](https://github.com/linewatch/linewatch) AI code reviews as markers on the lines in your editor.

## How it works

- Watches `.linewatch/last.sarif` in each workspace folder. Linewatch writes this file after every review, from a git hook or `linewatch review`.
- Shows each finding on its line, like a linter warning: critical as an error, warning as a warning, info as a hint. The suggested fix is part of the message.
- A review with no findings clears the markers.

## Commands

- `Linewatch: Show Status` shows how many findings the last review left.
- `Linewatch: Reload Findings` reads the SARIF file again.
