"""Measuring how well the branches that should log are covered by log calls."""

import io
import tokenize
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from birling.analysis import Branch, Unit, collect_units
from birling.config import Config


class MeasurementError(Exception):
    """A module that cannot be measured; the message names it and says why.

    Args:
        path: The module, or the directory that cannot be searched.
        problem: What is wrong with it.
    """

    def __init__(self, path: Path, problem: str) -> None:
        super().__init__(f"{path}: {problem}")


@dataclass(frozen=True)
class UnitMeasurement:
    """A unit with its branches that should log."""

    unit: Unit
    """The function or method measured."""

    branches: tuple[Branch, ...]
    """The unit's branches that should log, whether they do or not."""

    @property
    def unlogged(self) -> tuple[Branch, ...]:
        """The branches that should log but hold no log call."""
        return tuple(branch for branch in self.branches if not branch.is_logged)

    @property
    def logged(self) -> tuple[Branch, ...]:
        """The branches that should log and hold a log call."""
        return tuple(branch for branch in self.branches if branch.is_logged)


@dataclass(frozen=True)
class Measurement:
    """The log coverage of a body of code."""

    units: tuple[UnitMeasurement, ...]
    """Every unit measured, including those with no branch that should log."""

    @classmethod
    def combine(cls, measurements: Iterable[Self]) -> Self:
        """Combine measurements into one.

        Args:
            measurements: The measurements to combine.

        Returns:
            The measurement of all the units they hold.
        """
        return cls(tuple(unit for measurement in measurements for unit in measurement.units))

    @property
    def branch_count(self) -> int:
        """The number of branches that should log."""
        return sum(len(unit.branches) for unit in self.units)

    @property
    def logged_count(self) -> int:
        """The number of branches that should log and do."""
        return self.branch_count - sum(len(unit.unlogged) for unit in self.units)

    @property
    def score(self) -> float:
        """The percentage of branches that should log and do; 100 when none should."""
        if not self.branch_count:
            return 100.0
        return 100 * self.logged_count / self.branch_count


def measure_source(source: str, config: Config | None = None) -> Measurement:
    """Measure the log coverage of a module's source.

    A branch should log when its kind is one the configuration names, unless it ends by
    raising: raising leaves the logging to whatever handles the exception.

    Args:
        source: The module's source.
        config: What counts as a log call and which branches should log; the defaults
            when omitted.

    Returns:
        The measurement of every unit in the module.
    """
    return _measure(source, config or Config())


def measure_paths(
    paths: Iterable[Path], config: Config | None = None
) -> dict[Path, Measurement]:
    """Measure the log coverage of Python modules, those under the given directories included.

    A directory is searched through, skipping hidden directories and virtual environments.

    Args:
        paths: The modules and directories to measure.
        config: What counts as a log call and which branches should log; the defaults
            when omitted.

    Returns:
        The measurement of each module, in the order of their paths.

    Raises:
        MeasurementError: When a directory cannot be searched, or a module cannot be read
            or parsed.
    """
    config = config or Config()
    modules: set[Path] = set()
    for path in paths:
        try:
            modules.update(_find_modules(path))
        except OSError as error:
            failed = Path(error.filename) if error.filename else path
            raise MeasurementError(failed, error.strerror or str(error)) from error
    measurements = {}
    for module in sorted(modules):
        source = _read_module(module)
        try:
            measurements[module] = _measure(source, config)
        except SyntaxError as error:
            raise MeasurementError(module, _to_problem(error)) from error
        except Exception as error:
            error.add_note(f"while measuring {module}")
            raise
    return measurements


def _read_module(module: Path) -> str:
    """Read a module's source, in the encoding it declares.

    Args:
        module: The module's path.

    Returns:
        The module's source.

    Raises:
        MeasurementError: When the module cannot be read, or its encoding declaration is
            invalid, or it cannot be decoded.
    """
    try:
        content = module.read_bytes()
    except OSError as error:
        raise MeasurementError(module, error.strerror or str(error)) from error
    try:
        # Read from bytes, so that an error in the encoding declaration does not name the file.
        encoding, _ = tokenize.detect_encoding(io.BytesIO(content).readline)
        return content.decode(encoding)
    except SyntaxError as error:
        raise MeasurementError(module, error.msg) from error
    except UnicodeDecodeError as error:
        raise MeasurementError(module, f"not valid {error.encoding}: {error.reason}") from error


def _to_problem(error: SyntaxError) -> str:
    """Describe a syntax error without the file's name.

    Args:
        error: The error.

    Returns:
        Its message, with its line when it has one.
    """
    line = f" at line {error.lineno}" if error.lineno else ""
    return f"{error.msg}{line}"


def _find_modules(path: Path) -> Iterator[Path]:
    """Yield a module, or the modules under a directory.

    Hidden directories and virtual environments are skipped: they hold someone else's code.
    A virtual environment is told by its `pyvenv.cfg` among the names in the directory, so
    that an unreadable directory fails on its own listing.

    Args:
        path: A module or a directory.

    Yields:
        The modules.
    """
    if not path.is_dir():
        yield path
        return
    children = list(path.iterdir())
    if any(child.name == "pyvenv.cfg" for child in children):
        return
    for child in children:
        if child.is_dir():
            if not child.name.startswith("."):
                yield from _find_modules(child)
        elif child.suffix == ".py":
            yield child


def _measure(source: str, config: Config) -> Measurement:
    """Measure a module's source.

    Args:
        source: The module's source.
        config: What counts as a log call and which branches should log.

    Returns:
        The measurement of every unit in the module.
    """
    units = collect_units(source, config)
    return Measurement(
        tuple(
            UnitMeasurement(unit, tuple(b for b in unit.branches if _should_log(b, config)))
            for unit in units
        )
    )


def _should_log(branch: Branch, config: Config) -> bool:
    """Tell whether a branch should log.

    It should when its kind is configured, unless it raises on every path, which leaves the
    logging to whatever handles the exception, or it is accepted without a log: by a
    `# birling: ignore` comment, or by catching only exceptions that never need one.

    Args:
        branch: The branch.
        config: Which kinds of branch should log, and which exceptions need no log.

    Returns:
        Whether the branch should log.
    """
    if branch.kind not in config.branches or branch.always_raises or branch.has_ignore_comment:
        return False
    ignored = {name.rpartition(".")[2] for name in config.ignore_exceptions}
    caught = {name.rpartition(".")[2] for name in branch.exceptions}
    return not caught or not caught <= ignored
