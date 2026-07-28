#!/usr/bin/env python3
"""Print the CHANGELOG.md section body for a given version.

Usage:
    python scripts/extract_changelog.py 0.2.0

Reads CHANGELOG.md (Keep a Changelog format) and writes the body of the
`## [<version>] - ...` section to stdout, without the heading itself.
Exits 0 with empty output if the section is not found, so callers can decide
how to handle a missing entry.
"""

from __future__ import annotations

import pathlib
import re
import sys


def extract(changelog: str, version: str) -> str:
    lines = changelog.splitlines()
    # Match "## [0.2.0]" optionally followed by " - DATE".
    start_re = re.compile(rf"^##\s*\[{re.escape(version)}\]")
    next_re = re.compile(r"^##\s")

    start: int | None = None
    for i, line in enumerate(lines):
        if start_re.match(line):
            start = i + 1
            break
    if start is None:
        return ""

    body: list[str] = []
    for line in lines[start:]:
        if next_re.match(line):
            break
        body.append(line)

    return "\n".join(body).strip()


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: extract_changelog.py <version>", file=sys.stderr)
        return 2
    version = sys.argv[1].lstrip("v")
    changelog_path = pathlib.Path(__file__).resolve().parent.parent / "CHANGELOG.md"
    text = changelog_path.read_text(encoding="utf-8")
    print(extract(text, version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
