"""Writing measurements up as a table, a row per module."""

import math
from collections.abc import Mapping
from pathlib import Path

from birling.analysis import Branch
from birling.measurement import Measurement

_HEADER = "Branches  Logged  Score  Unlogged"


def to_text(
    measurements: Mapping[Path, Measurement],
    executed: Mapping[Path, frozenset[int]] | None = None,
) -> str:
    """Return a table of the modules with branches that should log, and their total.

    A module's row lists the lines of its branches that should log but do not. Scores are
    rounded down, so 100% means that every branch that should log does.

    Args:
        measurements: The measurement of each module, by path.
        executed: The lines that ran in the tests, by resolved path; when given, the lines
            of the unlogged branches that ran are marked with `*`.

    Returns:
        The table, a line per row.
    """
    modules = [
        (str(path), m, _find_ran(path, executed))
        for path, m in measurements.items()
        if m.branch_count
    ]
    width = max([len("TOTAL"), *(len(name) for name, _, _ in modules)])
    header = f"{'Name':<{width}}  {_HEADER}"
    rule = "-" * len(header)
    rows = [_to_row(name, m, width, _to_lines(m, ran)) for name, m, ran in modules]
    total = Measurement.combine(measurements.values())
    lines = [header, rule, *rows, *([rule] if rows else []), _to_row("TOTAL", total, width, "")]
    if executed is not None:
        ran = sum(b.body_line in ran for _, m, ran in modules for b in _find_unlogged(m))
        unlogged = total.branch_count - total.logged_count
        lines += ["", f"* ran in the tests: {ran} of {unlogged} unlogged branches"]
    return "\n".join(line.rstrip() for line in lines) + "\n"


def to_listing(
    measurements: Mapping[Path, Measurement],
    executed: Mapping[Path, frozenset[int]] | None = None,
) -> str:
    """Return a line for each branch that should log but does not.

    Each line reads `path:line: unit: branch`, which editors and CI logs turn into a link,
    in the order of the modules and of the branches' lines.

    Args:
        measurements: The measurement of each module, by path.
        executed: The lines that ran in the tests, by resolved path; when given, the
            branches that ran are marked as such.

    Returns:
        The listing, a line per branch; empty when every branch that should log does.
    """
    lines = []
    for path, measurement in measurements.items():
        ran = _find_ran(path, executed)
        names = {
            branch: measured.unit.name
            for measured in measurement.units
            for branch in measured.unlogged
        }
        for branch in _find_unlogged(measurement):
            what = f"{branch.kind} {branch.condition}".rstrip()
            mark = " (ran in the tests)" if branch.body_line in ran else ""
            lines.append(f"{path}:{branch.line}: {names[branch]}: {what}{mark}\n")
    return "".join(lines)


def _find_ran(path: Path, executed: Mapping[Path, frozenset[int]] | None) -> frozenset[int]:
    """Return the lines of a module that ran in the tests.

    Args:
        path: The module's path.
        executed: The lines that ran, by resolved path, if known.

    Returns:
        The lines; none when there is no coverage data or the module is not in it.
    """
    return frozenset() if executed is None else executed.get(path.resolve(), frozenset())


def _find_unlogged(measurement: Measurement) -> list[Branch]:
    """Return a module's branches that should log but do not.

    Args:
        measurement: The module's measurement.

    Returns:
        The branches, in the order of their lines.
    """
    branches = (branch for unit in measurement.units for branch in unit.unlogged)
    return sorted(branches, key=lambda branch: branch.line)


def _to_row(name: str, measurement: Measurement, width: int, unlogged: str) -> str:
    """Format a row of the table.

    Args:
        name: The module's path, or `TOTAL`.
        measurement: What the row counts.
        width: The width of the name column.
        unlogged: The lines of the unlogged branches, as listed.

    Returns:
        The row.
    """
    score = math.floor(measurement.score)
    counts = f"{measurement.branch_count:>8}  {measurement.logged_count:>6}  {score:>4}%"
    return f"{name:<{width}}  {counts}  {unlogged}"


def _to_lines(measurement: Measurement, ran: frozenset[int]) -> str:
    """List the lines that open a module's unlogged branches, marking those that ran with `*`.

    A branch ran when its first statement did.

    Args:
        measurement: The module's measurement.
        ran: The module's lines that ran in the tests.

    Returns:
        The lines, separated by commas.
    """
    branches = _find_unlogged(measurement)
    return ", ".join(f"{b.line}*" if b.body_line in ran else str(b.line) for b in branches)
