"""Command-line entry point for Linewatch."""

from __future__ import annotations

import argparse

from linewatch import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="linewatch",
        description="AI code review that runs in your git hooks.",
    )
    parser.add_argument(
        "--version", action="version", version=f"linewatch {__version__}"
    )
    commands = parser.add_subparsers(dest="command", metavar="command")
    init = commands.add_parser("init", help="setup wizard: model, hook, blocking levels")
    init.add_argument(
        "--yes",
        action="store_true",
        help="set up without questions, for joining a repo that is already configured",
    )
    commands.add_parser("model", help="switch to another model")
    # Called by the installed git hooks, not by devs.
    hook = commands.add_parser("hook")
    hook.add_argument("name", choices=["pre-commit", "pre-push"])
    hook.add_argument("git_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    if args.command == "hook":
        from linewatch import hooks

        return hooks.run_hook(args.name)
    if args.command == "init":
        from linewatch import wizard

        return wizard.run_init(yes=args.yes)
    if args.command == "model":
        from linewatch import wizard

        return wizard.run_model()

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
