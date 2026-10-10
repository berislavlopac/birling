"""Telling log calls from other calls."""

import ast
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Self

from birling.config import Config
from birling.syntax import to_dotted_name, walk_scope

# The method that takes its level from its first argument, as in `log.log(logging.INFO, ...)`.
_LEVEL_ARGUMENT_METHOD = "log"

# A name that reads as a logger's: `log`, `logger`, `_log`, `access_logger`, in any case.
_LOGGER_NAME = re.compile(r"(^|_)(log|logger)$", re.IGNORECASE)


@dataclass(frozen=True)
class LogCall:
    """A call that logs."""

    line: int
    """The line the call starts on."""

    level: str | None
    """The level it logs at, or `None` when the level is a value known only at runtime."""


@dataclass(frozen=True)
class LoggerScope:
    """The names that refer to loggers at one point in a module."""

    modules: frozenset[str] = frozenset()
    """Names bound to modules that log through functions of their own."""

    loggers: frozenset[str] = frozenset()
    """Names and dotted names, such as `self.logger`, bound to loggers."""

    functions: Mapping[str, str] = field(default_factory=dict)
    """Names bound to logging functions imported by name, each with the function's own name."""

    def with_loggers(self, loggers: Iterable[str]) -> Self:
        """Return a copy that also takes `loggers` for loggers.

        Args:
            loggers: Names and dotted names bound to loggers.

        Returns:
            The wider scope.
        """
        return replace(self, loggers=self.loggers | frozenset(loggers))


def find_module_scope(module: ast.Module, config: Config) -> LoggerScope:
    """Return the loggers and logging modules a module creates at its top level or imports.

    Args:
        module: The module's syntax tree.
        config: What counts as a logger.

    Returns:
        The names that refer to loggers throughout the module.
    """
    partitions = (dotted.rpartition(".") for dotted in config.logger_objects)
    objects = {(source, name) for source, _, name in partitions}
    modules: set[str] = set()
    loggers = set(find_loggers(walk_scope(module.body), config))
    functions: dict[str, str] = {}
    for node in ast.walk(module):
        match node:
            case ast.Import(names=aliases):
                for alias in aliases:
                    bound = alias.asname or alias.name
                    if alias.name in config.logger_modules:
                        modules.add(bound)
                    loggers.update(
                        f"{bound}.{name}" for source, name in objects if source == alias.name
                    )
            case ast.ImportFrom(module=source, names=aliases):
                for alias in aliases:
                    bound = alias.asname or alias.name
                    if (source, alias.name) in objects:
                        loggers.add(bound)
                    elif source in config.logger_modules and _logs(alias.name, config):
                        functions[bound] = alias.name
    return LoggerScope(frozenset(modules), frozenset(loggers), functions)


def find_loggers(nodes: Iterable[ast.AST], config: Config) -> frozenset[str]:
    """Return the names and dotted names that the assignments among `nodes` give a new logger.

    Only the nodes given are looked at, not their descendants.

    Args:
        nodes: The nodes to look at, such as those `walk_scope()` yields.
        config: What counts as a logger.

    Returns:
        Names such as `log`, and dotted names such as `self.logger`.
    """
    found: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if _creates_logger(value, config):
            found.update(name for target in targets if (name := to_dotted_name(target)))
    return frozenset(found)


def recognise(call: ast.Call, scope: LoggerScope, config: Config) -> LogCall | None:
    """Return the log call that `call` is, or `None` if it does not log.

    Args:
        call: The call to recognise.
        scope: The names that refer to loggers where the call is made.
        config: What counts as a log call.

    Returns:
        The log call, or `None`.
    """
    func = call.func
    helper = _to_last_name(func)
    if helper is not None and helper in config.helpers:
        return LogCall(call.lineno, config.helpers[helper])
    if isinstance(func, ast.Name) and func.id in scope.functions:
        return _to_log_call(call, scope.functions[func.id], config)
    if isinstance(func, ast.Attribute) and _is_logger(func.value, scope, config):
        return _to_log_call(call, func.attr, config)
    return None


def _to_log_call(call: ast.Call, function: str, config: Config) -> LogCall | None:
    """Return the log call that a call to a logging function or method is.

    Args:
        call: The call.
        function: The name of the function or method called.
        config: What counts as a log call.

    Returns:
        The log call, or `None` if the function does not log.
    """
    if function == _LEVEL_ARGUMENT_METHOD:
        return LogCall(call.lineno, _to_level(call.args, config))
    if function in config.level_methods:
        return LogCall(call.lineno, config.level_methods[function])
    return None


def _logs(function: str, config: Config) -> bool:
    """Tell whether a logging module's function logs, as `warning` does and `getLogger` not.

    Args:
        function: The function's name.
        config: The names of the functions that log.

    Returns:
        Whether the function logs.
    """
    return function == _LEVEL_ARGUMENT_METHOD or function in config.level_methods


def _is_logger(receiver: ast.expr, scope: LoggerScope, config: Config) -> bool:
    """Tell whether the expression a method is called on is a logger.

    It is one when it creates or binds a logger itself, when its name is in scope, or, with
    the name fallback, when its name reads as a logger's.

    Args:
        receiver: The expression.
        scope: The loggers known where it is.
        config: What counts as a logger.

    Returns:
        Whether it is a logger.
    """
    while (
        isinstance(receiver, ast.Call)
        and isinstance(receiver.func, ast.Attribute)
        and receiver.func.attr in config.binding_methods
    ):
        receiver = receiver.func.value
    if _creates_logger(receiver, config):
        return True
    name = to_dotted_name(receiver)
    if name is None:
        return False
    if name in scope.modules or name in scope.loggers:
        return True
    return config.name_fallback and bool(_LOGGER_NAME.search(name.rpartition(".")[2]))


def _creates_logger(node: ast.expr, config: Config) -> bool:
    """Tell whether an expression calls a logger factory.

    Args:
        node: The expression.
        config: The names of the logger factories.

    Returns:
        Whether it creates a logger.
    """
    return isinstance(node, ast.Call) and _to_last_name(node.func) in config.logger_factories


def _to_last_name(node: ast.expr) -> str | None:
    """Return the last part of a name or attribute, as `info` for `log.info`.

    Args:
        node: The expression.

    Returns:
        The last part, or `None` for any other expression.
    """
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
    return None


def _to_level(arguments: list[ast.expr], config: Config) -> str | None:
    """Return the level that the first argument of a `log` call names.

    Args:
        arguments: The call's arguments.
        config: The level names.

    Returns:
        The level, or `None` when it is known only at runtime.
    """
    name = to_dotted_name(arguments[0]) if arguments else None
    if name is None:
        return None
    return config.level_methods.get(name.rpartition(".")[2].lower())
