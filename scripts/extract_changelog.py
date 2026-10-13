"""Print the release notes of one version, from its section of `CHANGELOG.md`.

The release job uses the notes for the GitHub release. A missing section fails the job
before anything is published.
"""

import argparse
import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).parent.parent / "CHANGELOG.md"


def extract_notes(changelog: str, version: str) -> str | None:
    """Return the notes of one version, without the heading of its section.

    Args:
        changelog: The text of the changelog.
        version: The version, as written in the heading of its section.

    Returns:
        The notes, ending in a single newline, or `None` when the changelog has no section
        for the version.
    """
    pattern = rf"(?ms)^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)"
    match = re.search(pattern, changelog)
    return None if match is None else match.group(1).strip() + "\n"


def main() -> None:
    """Print the notes of the version named on the command line, or exit with status 1."""
    parser = argparse.ArgumentParser(description="Print the release notes of one version.")
    parser.add_argument("version", help="the version, such as 0.1.0")
    args = parser.parse_args()
    notes = extract_notes(CHANGELOG.read_text(encoding="utf-8"), args.version)
    if notes is None:
        sys.exit(f"{CHANGELOG.name} has no section for {args.version}")
    print(notes, end="")


if __name__ == "__main__":
    main()
