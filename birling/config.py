"""What counts as a log call, which branches should log, and the lowest acceptable score."""

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from enum import StrEnum
from pathlib import Path
import tomllib
from typing import Self

# Where the configuration sits in `pyproject.toml`, used to name a key in an error.
_TABLE = "tool.birling"

# Scores are percentages.
_FULL_SCORE = 100


class ConfigError(ValueError):
    """A `[tool.birling]` table that cannot be read; the message names the key at fault.

    Args:
        key: The key at fault, or `None` for the table as a whole.
        problem: What is wrong with it.
    """

    def __init__(self, key: str | None, problem: str) -> None:
        super().__init__(f"{_TABLE}.{key}: {problem}" if key else f"{_TABLE}: {problem}")


class BranchKind(StrEnum):
    """A kind of branch: one of several alternative paths through a function."""

    EXCEPT = "except"
    """An `except` or `except*` handler."""

    IF = "if"
    """The body of an `if` or an `elif`."""

    ELSE = "else"
    """The `else` of an `if`."""

    CASE = "case"
    """A `case` of a `match`."""

    TRY_ELSE = "try-else"
    """The `else` of a `try`, which runs when nothing was raised."""

    LOOP_ELSE = "loop-else"
    """The `else` of a `for` or `while`, which runs when the loop ends without `break`."""


_STANDARD_LEVEL_METHODS = {
    "debug": "debug",
    "info": "info",
    "warning": "warning",
    "warn": "warning",
    "error": "error",
    "exception": "exception",
    "critical": "critical",
    "fatal": "critical",
}


@dataclass(frozen=True)
class Config:
    """What counts as a log call, which branches should log, and the lowest acceptable score."""

    branches: frozenset[BranchKind] = frozenset({BranchKind.EXCEPT})
    """The kinds of branch that should log, unless they end by raising."""

    ignore_exceptions: frozenset[str] = frozenset()
    """Exception types that never need a log, matched by the last part of their names.

    A handler that catches only these need not log.
    """

    level_methods: Mapping[str, str] = field(
        default_factory=lambda: dict(_STANDARD_LEVEL_METHODS)
    )
    """Method names that log, each with the level it logs at.

    A `log` method is recognised as well, taking its level from its first argument.
    """

    logger_factories: frozenset[str] = frozenset(
        {"getLogger", "get_logger", "getChild", "LoggerAdapter"}
    )
    """Names of the functions, classes and methods that create a logger."""

    logger_modules: frozenset[str] = frozenset({"logging"})
    """Modules that log through functions of their own, as in `logging.warning(...)`."""

    logger_objects: frozenset[str] = frozenset()
    """Loggers imported from a module, each written as `module.name`."""

    binding_methods: frozenset[str] = frozenset({"bind", "new", "opt"})
    """Methods that return a logger derived from the one they are called on."""

    helpers: Mapping[str, str] = field(default_factory=dict)
    """Names of the project's own functions that log, each with the level it logs at."""

    name_fallback: bool = True
    """Whether a receiver named like a logger, such as `log` or `self._logger`, is one."""

    module_level: bool = False
    """Whether a module's own code, outside its functions and classes, is measured as a unit."""

    lambdas: bool = False
    """Whether a log call in a lambda counts for the code the lambda is written in."""

    fail_under: float = 0
    """The lowest acceptable score, as a percentage; the command fails below it."""

    @classmethod
    def from_table(cls, table: Mapping[str, object]) -> Self:
        """Build a configuration from a `[tool.birling]` table.

        The keys are the field names in kebab case. The recognition entries add to the
        defaults, while `branches` replaces them.

        Args:
            table: The table, as read from `pyproject.toml`.

        Returns:
            The configuration, with the defaults for the keys the table leaves out.

        Raises:
            ConfigError: When a key is unknown or a value is not of the expected type.
        """
        unknown = sorted(table.keys() - {f.name.replace("_", "-") for f in fields(cls)})
        if unknown:
            raise ConfigError(unknown[0], "unknown key")
        defaults = cls()
        return cls(
            branches=_read_kinds(table, defaults.branches),
            ignore_exceptions=_read_names(table, "ignore-exceptions"),
            level_methods={**defaults.level_methods, **_read_levels(table, "level-methods")},
            logger_factories=defaults.logger_factories | _read_names(table, "logger-factories"),
            logger_modules=defaults.logger_modules | _read_names(table, "logger-modules"),
            logger_objects=defaults.logger_objects | _read_names(table, "logger-objects"),
            binding_methods=defaults.binding_methods | _read_names(table, "binding-methods"),
            helpers=_read_levels(table, "helpers"),
            name_fallback=_read_flag(table, "name-fallback", defaults.name_fallback),
            module_level=_read_flag(table, "module-level", defaults.module_level),
            lambdas=_read_flag(table, "lambdas", defaults.lambdas),
            fail_under=_read_score(table, "fail-under", defaults.fail_under),
        )

    @classmethod
    def from_pyproject(cls, path: Path) -> Self:
        """Read the configuration from the `[tool.birling]` table of a `pyproject.toml`.

        Args:
            path: The `pyproject.toml` file.

        Returns:
            The configuration; the defaults when the file has no such table.

        Raises:
            ConfigError: When `tool.birling` is not a table.
        """
        with path.open("rb") as file:
            document = tomllib.load(file)
        table = document.get("tool", {}).get("birling", {})
        if not isinstance(table, dict):
            raise ConfigError(None, "expected a table")
        return cls.from_table(table)


def _read_kinds(
    table: Mapping[str, object], default: frozenset[BranchKind]
) -> frozenset[BranchKind]:
    """Read the kinds of branch that should log.

    Args:
        table: The `[tool.birling]` table.
        default: The kinds when the table leaves them out.

    Returns:
        The kinds.

    Raises:
        ConfigError: When a name is not a kind of branch.
    """
    if "branches" not in table:
        return default
    names = _read_names(table, "branches")
    unknown = sorted(names - set(BranchKind))
    if unknown:
        known = ", ".join(BranchKind)
        raise ConfigError("branches", f"unknown {', '.join(unknown)}; expected one of {known}")
    return frozenset(BranchKind(name) for name in names)


def _read_names(table: Mapping[str, object], key: str) -> frozenset[str]:
    """Read a list of names.

    Args:
        table: The `[tool.birling]` table.
        key: The key of the list.

    Returns:
        The names; none when the table leaves the key out.

    Raises:
        ConfigError: When the value is not a list of strings.
    """
    value = table.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(key, "expected a list of strings")
    return frozenset(value)


def _read_levels(table: Mapping[str, object], key: str) -> dict[str, str]:
    """Read a table of names, each with the level it logs at.

    Args:
        table: The `[tool.birling]` table.
        key: The key of the table.

    Returns:
        The levels by name; none when the table leaves the key out.

    Raises:
        ConfigError: When the value is not a table of strings.
    """
    value = table.get(key, {})
    if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
        raise ConfigError(key, "expected a table of level names")
    return dict(value)


def _read_flag(table: Mapping[str, object], key: str, default: bool) -> bool:
    """Read a switch.

    Args:
        table: The `[tool.birling]` table.
        key: The key of the switch.
        default: The value when the table leaves the key out.

    Returns:
        Whether the switch is on.

    Raises:
        ConfigError: When the value is not a boolean.
    """
    value = table.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(key, "expected true or false")
    return value


def _read_score(table: Mapping[str, object], key: str, default: float) -> float:
    """Read a score.

    Args:
        table: The `[tool.birling]` table.
        key: The key of the score.
        default: The value when the table leaves the key out.

    Returns:
        The score, as a percentage.

    Raises:
        ConfigError: When the value is not a number from 0 to 100.
    """
    value = table.get(key, default)
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not 0 <= value <= _FULL_SCORE
    ):
        raise ConfigError(key, "expected a number from 0 to 100")
    return value
