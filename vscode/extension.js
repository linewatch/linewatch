"use strict";

const vscode = require("vscode");
const { parseFindings, diagnosticMessage } = require("./sarif");

const SARIF_PATH = ".linewatch/last.sarif";

// critical as an error, warning as a warning, info as a hint (use case 17).
const SEVERITY = {
  critical: vscode.DiagnosticSeverity.Error,
  warning: vscode.DiagnosticSeverity.Warning,
  info: vscode.DiagnosticSeverity.Hint,
};

function activate(context) {
  const diagnostics = vscode.languages.createDiagnosticCollection("linewatch");
  context.subscriptions.push(diagnostics);

  // One SARIF file per workspace folder, so markers are tracked per folder.
  const byFolder = new Map();

  function render() {
    diagnostics.clear();
    const perFile = new Map();
    for (const entries of byFolder.values()) {
      for (const [uri, diagnostic] of entries) {
        const key = uri.toString();
        if (!perFile.has(key)) perFile.set(key, { uri, list: [] });
        perFile.get(key).list.push(diagnostic);
      }
    }
    for (const { uri, list } of perFile.values()) diagnostics.set(uri, list);
  }

  async function load(folder) {
    const sarifUri = vscode.Uri.joinPath(folder.uri, SARIF_PATH);
    let text;
    try {
      text = Buffer.from(await vscode.workspace.fs.readFile(sarifUri)).toString("utf8");
    } catch {
      byFolder.delete(folder.uri.toString());
      render();
      return;
    }
    const findings = parseFindings(text);
    if (findings === null) return;
    byFolder.set(
      folder.uri.toString(),
      findings.map((f) => {
        // Mark the whole line; VS Code clamps the end to the line's length.
        const range = new vscode.Range(f.line - 1, 0, f.line - 1, Number.MAX_SAFE_INTEGER);
        const diagnostic = new vscode.Diagnostic(
          range,
          diagnosticMessage(f),
          SEVERITY[f.severity] ?? vscode.DiagnosticSeverity.Warning
        );
        diagnostic.source = "Linewatch";
        diagnostic.code = `${f.severity}/${f.category}`;
        return [vscode.Uri.joinPath(folder.uri, f.file), diagnostic];
      })
    );
    render();
  }

  function watch(folder) {
    const watcher = vscode.workspace.createFileSystemWatcher(
      new vscode.RelativePattern(folder, SARIF_PATH)
    );
    watcher.onDidCreate(() => load(folder));
    watcher.onDidChange(() => load(folder));
    watcher.onDidDelete(() => load(folder));
    context.subscriptions.push(watcher);
    load(folder);
  }

  for (const folder of vscode.workspace.workspaceFolders || []) watch(folder);
  context.subscriptions.push(
    vscode.workspace.onDidChangeWorkspaceFolders((event) => {
      for (const folder of event.added) watch(folder);
      for (const folder of event.removed) byFolder.delete(folder.uri.toString());
      render();
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("linewatch.showStatus", () => {
      let count = 0;
      diagnostics.forEach((_, list) => (count += list.length));
      vscode.window.showInformationMessage(
        count
          ? `Linewatch: ${count} finding(s) from the last review.`
          : "Linewatch: no findings from the last review."
      );
    }),
    vscode.commands.registerCommand("linewatch.reload", () => {
      for (const folder of vscode.workspace.workspaceFolders || []) load(folder);
    })
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
