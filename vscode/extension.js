"use strict";

const vscode = require("vscode");

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("linewatch.showStatus", () => {
      vscode.window.showInformationMessage(
        "Linewatch 0.0.1: early placeholder release. Line findings are under development."
      );
    })
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
