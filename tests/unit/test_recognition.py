import ast
from textwrap import dedent

import pytest

from birling.config import Config
from birling.recognition import (
    LogCall,
    LoggerScope,
    find_loggers,
    find_module_scope,
    recognise,
)
from birling.syntax import walk_scope


def test_recognise_returns_the_level_a_logger_method_logs_at():
    call = ast.parse("log.warning('disk full')", mode="eval").body
    scope = LoggerScope(modules=frozenset(), loggers=frozenset({"log"}))
    config = Config()

    log_call = recognise(call, scope, config)

    assert log_call == LogCall(line=1, level="warning")


@pytest.mark.parametrize(
    ("method", "level"),
    [
        ("debug", "debug"),
        ("info", "info"),
        ("warning", "warning"),
        ("warn", "warning"),
        ("error", "error"),
        ("exception", "exception"),
        ("critical", "critical"),
        ("fatal", "critical"),
    ],
)
def test_recognise_knows_the_standard_level_methods(method, level):
    call = ast.parse(f"log.{method}('message')", mode="eval").body

    log_call = recognise(call, LoggerScope(loggers=frozenset({"log"})), Config())

    assert log_call == LogCall(line=1, level=level)


def test_recognise_takes_a_logging_module_function_for_a_log_call():
    call = ast.parse("std_logging.error('disk full')", mode="eval").body

    log_call = recognise(call, LoggerScope(modules=frozenset({"std_logging"})), Config())

    assert log_call == LogCall(line=1, level="error")


@pytest.mark.parametrize(
    "expression",
    [
        "logging.getLogger(__name__).info('started')",
        "structlog.get_logger().bind(user=1).opt(lazy=True).info('started')",
        "log.bind(user=1).info('started')",
    ],
    ids=["created in the call", "created and bound in the call", "bound in the call"],
)
def test_recognise_follows_a_logger_created_or_bound_in_the_call(expression):
    call = ast.parse(expression, mode="eval").body

    log_call = recognise(call, LoggerScope(loggers=frozenset({"log"})), Config())

    assert log_call == LogCall(line=1, level="info")


@pytest.mark.parametrize(
    ("expression", "level"),
    [("warn('disk full')", "warning"), ("log_at(logging.ERROR, 'disk full')", "error")],
)
def test_recognise_takes_a_logging_function_imported_by_name_for_a_log_call(expression, level):
    call = ast.parse(expression, mode="eval").body
    scope = LoggerScope(functions={"warn": "warning", "log_at": "log"})

    log_call = recognise(call, scope, Config())

    assert log_call == LogCall(line=1, level=level)


@pytest.mark.parametrize(
    ("argument", "level"),
    [("logging.WARNING", "warning"), ("FATAL", "critical"), ("level", None), ("20", None)],
)
def test_recognise_takes_the_level_of_log_from_its_first_argument(argument, level):
    call = ast.parse(f"log.log({argument}, 'message')", mode="eval").body

    log_call = recognise(call, LoggerScope(loggers=frozenset({"log"})), Config())

    assert log_call == LogCall(line=1, level=level)


@pytest.mark.parametrize("receiver", ["logger", "LOG", "self._log", "self.access_logger"])
def test_recognise_takes_a_receiver_named_like_a_logger_for_one(receiver):
    call = ast.parse(f"{receiver}.info('started')", mode="eval").body

    log_call = recognise(call, LoggerScope(), Config())

    assert log_call == LogCall(line=1, level="info")


def test_recognise_ignores_the_name_of_a_receiver_when_the_fallback_is_off():
    call = ast.parse("self.logger.info('started')", mode="eval").body

    log_call = recognise(call, LoggerScope(), Config(name_fallback=False))

    assert log_call is None


@pytest.mark.parametrize(
    "expression",
    [
        "response.info()",
        "catalog.info()",
        "parser.error('bad option')",
        "task.exception()",
        "warnings.warn('deprecated')",
        "error('not a method')",
        "log.flush()",
    ],
)
def test_recognise_rejects_a_call_that_is_not_a_log_call(expression):
    call = ast.parse(expression, mode="eval").body

    log_call = recognise(call, LoggerScope(loggers=frozenset({"log"})), Config())

    assert log_call is None


@pytest.mark.parametrize("expression", ["loggers['events'].info('a')", "make()().info('a')"])
def test_recognise_does_not_follow_a_receiver_that_is_not_a_name(expression):
    """Indexed and called receivers are not followed, even when they would hold a logger."""
    call = ast.parse(expression, mode="eval").body

    log_call = recognise(call, LoggerScope(), Config(name_fallback=False))

    assert log_call is None


@pytest.mark.parametrize("expression", ["log_failure('failed')", "self.log_failure('failed')"])
def test_recognise_takes_a_configured_helper_for_a_log_call_at_its_level(expression):
    call = ast.parse(expression, mode="eval").body

    log_call = recognise(call, LoggerScope(), Config(helpers={"log_failure": "error"}))

    assert log_call == LogCall(line=1, level="error")


def test_recognise_knows_a_configured_level_method():
    call = ast.parse("logger.success('done')", mode="eval").body
    config = Config(level_methods={**Config().level_methods, "success": "success"})

    log_call = recognise(call, LoggerScope(loggers=frozenset({"logger"})), config)

    assert log_call == LogCall(line=1, level="success")


def test_find_loggers_returns_the_names_and_attributes_assigned_a_new_logger():
    source = dedent("""
        log = logging.getLogger(__name__)
        events: Logger = structlog.get_logger("events")
        self.logger = logging.getLogger("service")
        child = log.getChild("child")
        other = make_something()
        self.passed_in = logger
    """)
    statements = ast.parse(source).body

    loggers = find_loggers(statements, Config())

    assert loggers == frozenset({"log", "events", "self.logger", "child"})


def test_find_loggers_looks_only_at_the_nodes_given():
    """The caller walks the code it wants searched, as `walk_scope()` does a scope."""
    source = dedent("""
        if DEBUG:
            log = logging.getLogger("debug")

        def inner():
            hidden = logging.getLogger(__name__)
    """)
    statements = ast.parse(source).body

    loggers = find_loggers(walk_scope(statements), Config())

    assert loggers == frozenset({"log"})


def test_find_loggers_knows_a_configured_factory():
    statements = ast.parse("flog = Logging(TRACE, 'main')").body
    config = Config(logger_factories=Config().logger_factories | {"Logging"})

    loggers = find_loggers(statements, config)

    assert loggers == frozenset({"flog"})


def test_find_module_scope_returns_the_loggers_and_logging_modules_of_a_module():
    source = dedent("""
        import logging
        import pyfastlogging as fl
        import loguru
        import loguru as lg
        from loguru import logger
        from loguru import logger as events
        from logging import getLogger, warning, log as log_at
        from json import dumps as log_json

        log = logging.getLogger(__name__)

        def run():
            local = logging.getLogger("local")
    """)
    module = ast.parse(source)
    config = Config(
        logger_modules=frozenset({"logging", "pyfastlogging"}),
        logger_objects=frozenset({"loguru.logger"}),
    )

    scope = find_module_scope(module, config)

    assert scope == LoggerScope(
        modules=frozenset({"logging", "fl"}),
        loggers=frozenset({"log", "loguru.logger", "lg.logger", "logger", "events"}),
        functions={"warning": "warning", "log_at": "log"},
    )


def test_a_logger_scope_with_more_loggers_is_a_copy():
    scope = LoggerScope(modules=frozenset({"logging"}), loggers=frozenset({"log"}))

    wider = scope.with_loggers(["self.logger"])

    assert wider == LoggerScope(
        modules=frozenset({"logging"}), loggers=frozenset({"log", "self.logger"})
    )
    assert scope.loggers == frozenset({"log"})
