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
    parser.parse_args(argv)
    print(
        f"linewatch {__version__}: early placeholder release. "
        "The review engine is under development."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
