"""The `birling` command."""

import argparse
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

from birling import __version__
from birling.config import Config, ConfigError
from birling.measurement import Measurement, MeasurementError, measure_paths
from birling.report import to_listing, to_text, to_unrun_listing
from birling.runtime import CoverageDataError, read_executed_lines

# Read when present and no other file is named.
_PYPROJECT = Path("pyproject.toml")

# The exit status of a run that could not measure, as for a usage error.
_ERROR_STATUS = 2


def main(argv: Sequence[str] | None = None) -> int:
    """Measure the log coverage of the paths given, print the report and judge the score.

    Args:
        argv: The arguments, without the program's name; the process's when omitted.

    Returns:
        The exit status: 1 when the total score is below the minimum, 2 when the
        configuration, a module or the coverage data cannot be read, and 0 otherwise.
    """
    parser = _to_parser()
    arguments = parser.parse_args(argv)
    if arguments.show_unrun_logs and not arguments.coverage_file:
        parser.error("--show-unrun-logs needs --coverage-file")
    pyproject = arguments.config or (_PYPROJECT if _PYPROJECT.exists() else None)
    try:
        config = Config.from_pyproject(pyproject) if pyproject else Config()
    except (ConfigError, OSError, tomllib.TOMLDecodeError) as error:  # birling: ignore
        return _fail(f"cannot read {pyproject}: {error}")
    try:
        measurements = measure_paths(arguments.paths, config)
    except MeasurementError as error:  # birling: ignore
        return _fail(f"cannot measure {error}")
    executed = None
    if arguments.coverage_file:
        try:
            executed = read_executed_lines(arguments.coverage_file)
        except CoverageDataError as error:  # birling: ignore
            return _fail(f"cannot read the coverage data in {error}")
    print(to_text(measurements, executed), end="")
    if arguments.show_unlogged and (listing := to_listing(measurements, executed)):
        print(f"\n{listing}", end="")
    if (
        arguments.show_unrun_logs
        and executed is not None
        and (listing := to_unrun_listing(measurements, executed))
    ):
        print(f"\n{listing}", end="")
    fail_under = config.fail_under if arguments.fail_under is None else arguments.fail_under
    score = Measurement.combine(measurements.values()).score
    if score < fail_under:
        message = f"score {score:.2f}% is below the minimum of {fail_under:g}%"
        print(f"birling: {message}", file=sys.stderr)
        return 1
    return 0


def _to_parser() -> argparse.ArgumentParser:
    """Build the command's argument parser.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="birling", description="Measure how well Python code is covered by log calls."
    )
    parser.add_argument(
        "paths", nargs="+", type=Path, metavar="PATH", help="modules and directories to measure"
    )
    parser.add_argument(
        "--config",
        type=Path,
        metavar="FILE",
        help="the pyproject.toml to read [tool.birling] from; by default ./pyproject.toml",
    )
    parser.add_argument(
        "--fail-under",
        type=float,
        metavar="SCORE",
        help="fail when the total score is below SCORE, overriding fail-under",
    )
    parser.add_argument(
        "--coverage-file",
        type=Path,
        metavar="FILE",
        help="coverage.py's data from a test run, to mark the unlogged branches that ran"
        " and count the logged branches where no log call ran",
    )
    parser.add_argument(
        "--show-unlogged",
        action="store_true",
        help="list each unlogged branch after the report, as path:line",
    )
    parser.add_argument(
        "--show-unrun-logs",
        action="store_true",
        help="list each logged branch whose log calls never ran; needs --coverage-file",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _fail(message: str) -> int:
    """Report an error on the standard error stream.

    Args:
        message: What went wrong.

    Returns:
        The exit status of a run that could not measure.
    """
    print(f"birling: error: {message}", file=sys.stderr)
    return _ERROR_STATUS
