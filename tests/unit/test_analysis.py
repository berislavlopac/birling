import ast
from textwrap import dedent, indent

import pytest

from birling.analysis import MODULE_UNIT_NAME, Branch, Unit, collect_units
from birling.config import BranchKind, Config
from birling.recognition import LogCall


def test_collect_units_returns_each_function_with_its_branches_and_log_calls():
    source = dedent("""
        import logging
        log = logging.getLogger(__name__)

        def handle(request):
            if not request:
                log.warning("empty request")
                return None
            try:
                result = process(request)
            except TimeoutError:
                return "timeout"
            except ValueError:
                log.exception("bad request")
                raise
            return result
    """)
    module = ast.parse(source)

    units = collect_units(module, Config())

    assert units == (
        Unit(
            name="handle",
            line=5,
            branches=(
                Branch(
                    kind=BranchKind.IF,
                    line=7,
                    condition="not request",
                    always_raises=False,
                    log_calls=(LogCall(line=7, level="warning"),),
                ),
                Branch(
                    kind=BranchKind.EXCEPT,
                    line=12,
                    condition="TimeoutError",
                    always_raises=False,
                    log_calls=(),
                ),
                Branch(
                    kind=BranchKind.EXCEPT,
                    line=14,
                    condition="ValueError",
                    always_raises=True,
                    log_calls=(LogCall(line=14, level="exception"),),
                ),
            ),
            log_calls=(LogCall(line=7, level="warning"), LogCall(line=14, level="exception")),
        ),
    )


@pytest.mark.parametrize(
    ("body", "kinds"),
    [
        ("if ready:\n    start()", [BranchKind.IF]),
        ("if ready:\n    start()\nelse:\n    stop()", [BranchKind.IF, BranchKind.ELSE]),
        ("try:\n    start()\nexcept OSError:\n    stop()", [BranchKind.EXCEPT]),
        ("try:\n    start()\nexcept* OSError:\n    stop()", [BranchKind.EXCEPT]),
        (
            "try:\n    start()\nexcept OSError:\n    stop()\nelse:\n    done()",
            [BranchKind.EXCEPT, BranchKind.TRY_ELSE],
        ),
        ("match ready:\n    case True:\n        start()", [BranchKind.CASE]),
        ("for item in items:\n    start()\nelse:\n    done()", [BranchKind.LOOP_ELSE]),
        ("while ready:\n    start()\nelse:\n    done()", [BranchKind.LOOP_ELSE]),
    ],
    ids=["if", "else", "except", "except*", "try-else", "case", "for-else", "while-else"],
)
def test_collect_units_finds_each_kind_of_branch(body, kinds):
    module = ast.parse("def run():\n" + indent(body, "    "))

    [run] = collect_units(module, Config())

    assert [branch.kind for branch in run.branches] == kinds


@pytest.mark.parametrize(
    "body",
    [
        "for item in items:\n    start()",
        "while ready:\n    start()",
        "with lock:\n    start()",
        "try:\n    start()\nfinally:\n    stop()",
        "value = start() if ready else stop()",
    ],
    ids=["loop", "while", "with", "finally", "conditional expression"],
)
def test_collect_units_finds_no_branch_in_a_block_that_always_runs_or_an_expression(body):
    module = ast.parse("def run():\n" + indent(body, "    "))

    [run] = collect_units(module, Config())

    assert run.branches == ()


@pytest.mark.parametrize(
    ("handler", "always_raises"),
    [
        ("raise", True),
        ("raise RuntimeError('failed') from error", True),
        ("log.warning('failed')\nraise", True),
        ("return None", False),
        ("continue", False),
        ("break", False),
        ("stop()", False),
        ("if error.args:\n    raise\nreturn None", False),
        ("if error.args:\n    return None\nraise", False),
        ("if error.args:\n    raise\nraise RuntimeError('failed')", True),
        ("if error.args:\n    raise\nelse:\n    raise RuntimeError('failed')", True),
        ("for retry in retries:\n    if retry():\n        break\nraise", True),
        ("for retry in retries:\n    if retry():\n        return None\nraise", False),
        ("for retry in retries:\n    retry()\nelse:\n    continue\nraise", False),
        ("with lock:\n    raise", True),
        ("try:\n    undo()\nexcept OSError:\n    raise\nelse:\n    raise", True),
        ("try:\n    undo()\nexcept OSError:\n    return None\nraise", False),
        ("try:\n    undo()\nexcept OSError:\n    raise\nfinally:\n    cleanup()", False),
        ("try:\n    undo()\nfinally:\n    raise", True),
        ("match error.args:\n    case []:\n        raise\n    case _:\n        raise", True),
        ("match error.args:\n    case []:\n        raise", False),
        (
            "match error.args:\n    case []:\n        raise\n    case _ if error:\n        raise",
            False,
        ),
        ("def retry():\n    return None\nraise", True),
    ],
)
def test_a_branch_always_raises_when_every_path_through_it_does(handler, always_raises):
    """A `return`, or a `break` or `continue` that leaves the loop around it, is a way out.

    The handler's own branch comes first, before any branch nested in it.
    """
    module = ast.parse(
        "def run(items):\n"
        "    for item in items:\n"
        "        try:\n"
        "            start(item)\n"
        "        except OSError as error:\n" + indent(handler, " " * 12)
    )

    run, *_nested = collect_units(module, Config())

    handler_branch = run.branches[0]
    assert handler_branch.always_raises is always_raises


def test_an_elif_is_an_if_branch_and_an_if_in_an_else_is_both():
    source = dedent("""
        def check(value):
            if value == 1:
                return 1
            elif value == 2:
                return 2
            else:
                if value == 3:
                    return 3
                return 4
    """)
    module = ast.parse(source)

    [check] = collect_units(module, Config())

    assert check.branches == (
        Branch(
            BranchKind.IF, line=4, condition="value == 1", always_raises=False, log_calls=()
        ),
        Branch(
            BranchKind.IF, line=6, condition="value == 2", always_raises=False, log_calls=()
        ),
        Branch(BranchKind.ELSE, line=8, condition="", always_raises=False, log_calls=()),
        Branch(
            BranchKind.IF, line=9, condition="value == 3", always_raises=False, log_calls=()
        ),
    )


def test_a_case_is_selected_by_its_pattern_and_guard():
    source = dedent("""
        def check(value):
            match value:
                case [first, *_] if first:
                    return first
                case _:
                    return None
    """)
    module = ast.parse(source)

    [check] = collect_units(module, Config())

    assert [branch.condition for branch in check.branches] == ["[first, *_] if first", "_"]


def test_a_bare_handler_has_no_condition():
    source = dedent("""
        def load(path):
            try:
                return read(path)
            except:
                return None
    """)
    module = ast.parse(source)

    [load] = collect_units(module, Config())

    assert [branch.condition for branch in load.branches] == [""]


def test_branches_are_listed_in_the_order_of_their_lines():
    source = dedent("""
        def load(path):
            try:
                return read(path)
            except OSError:
                if path:
                    return None
                return ""
            except ValueError:
                return None
    """)
    module = ast.parse(source)

    [load] = collect_units(module, Config())

    assert [(branch.kind, branch.line) for branch in load.branches] == [
        (BranchKind.EXCEPT, 6),
        (BranchKind.IF, 7),
        (BranchKind.EXCEPT, 10),
    ]


def test_a_log_call_in_a_nested_statement_belongs_to_the_branch():
    source = dedent("""
        import logging

        def load(path):
            try:
                return read(path)
            except OSError:
                if path:
                    logging.warning("cannot read %s", path)
                return None
    """)
    module = ast.parse(source)

    [load] = collect_units(module, Config())

    assert [branch.log_calls for branch in load.branches] == [
        (LogCall(line=9, level="warning"),),
        (LogCall(line=9, level="warning"),),
    ]


def test_a_log_call_in_a_lambda_belongs_to_neither_branch_nor_unit_by_default():
    """A lambda's body runs when it is called, not where it is written."""
    source = dedent("""
        import logging

        def load(path, on_error):
            try:
                return read(path)
            except OSError:
                on_error(lambda: logging.warning("cannot read %s", path))
                return None
    """)
    module = ast.parse(source)

    [load] = collect_units(module, Config())

    assert ([branch.log_calls for branch in load.branches], load.log_calls) == ([()], ())


def test_a_log_call_in_a_lambda_belongs_to_its_branch_and_unit_when_configured():
    source = dedent("""
        import logging

        def load(path, on_error):
            try:
                return read(path)
            except OSError:
                on_error(lambda: logging.warning("cannot read %s", path))
                return None
    """)
    module = ast.parse(source)

    [load] = collect_units(module, Config(lambdas=True))

    warning = LogCall(line=8, level="warning")
    assert ([branch.log_calls for branch in load.branches], load.log_calls) == (
        [(warning,)],
        (warning,),
    )


def test_a_nested_function_is_a_unit_of_its_own_and_sees_the_loggers_around_it():
    source = dedent("""
        import logging

        def outer():
            events = logging.getLogger("events")

            def inner():
                events.info("inner")

            events.info("outer")
            return inner
    """)
    module = ast.parse(source)

    units = collect_units(module, Config(name_fallback=False))

    assert [(unit.name, unit.log_calls) for unit in units] == [
        ("outer", (LogCall(line=10, level="info"),)),
        ("outer.inner", (LogCall(line=8, level="info"),)),
    ]


def test_methods_are_named_after_their_class_and_share_its_logger_attributes():
    source = dedent("""
        import logging

        class Service:
            def __init__(self):
                self.events = logging.getLogger("service")

            def run(self):
                self.events.info("running")

            class Worker:
                async def start(self):
                    pass
    """)
    module = ast.parse(source)

    units = collect_units(module, Config(name_fallback=False))

    assert [(unit.name, unit.log_calls) for unit in units] == [
        ("Service.__init__", ()),
        ("Service.run", (LogCall(line=9, level="info"),)),
        ("Service.Worker.start", ()),
    ]


def test_functions_defined_under_a_module_level_statement_are_units():
    source = dedent("""
        import sys

        if sys.version_info >= (3, 12):
            def run():
                pass
        else:
            def run():
                pass
    """)
    module = ast.parse(source)

    units = collect_units(module, Config())

    assert [(unit.name, unit.line) for unit in units] == [("run", 5), ("run", 8)]


def test_module_level_code_is_not_part_of_a_unit_by_default():
    source = dedent("""
        try:
            import fast_json as json
        except ImportError:
            import json
    """)
    module = ast.parse(source)

    units = collect_units(module, Config())

    assert units == ()


def test_module_level_code_is_a_unit_of_its_own_when_configured():
    source = dedent("""
        import logging
        log = logging.getLogger(__name__)

        try:
            import fast_json as json
        except ImportError:
            log.info("using the standard json")
            import json

        def load(path):
            if path:
                return json.loads(read(path))
    """)
    module = ast.parse(source)

    units = collect_units(module, Config(module_level=True))

    assert [unit.name for unit in units] == [MODULE_UNIT_NAME, "load"]
    assert units[0] == Unit(
        name="<module>",
        line=1,
        branches=(
            Branch(
                kind=BranchKind.EXCEPT,
                line=8,
                condition="ImportError",
                always_raises=False,
                log_calls=(LogCall(line=8, level="info"),),
            ),
        ),
        log_calls=(LogCall(line=8, level="info"),),
    )


def test_a_branch_is_logged_when_it_holds_a_log_call():
    logged = Branch(
        kind=BranchKind.EXCEPT,
        line=12,
        condition="OSError",
        always_raises=False,
        log_calls=(LogCall(line=12, level="warning"),),
    )

    is_logged = logged.is_logged

    assert is_logged


def test_a_branch_is_not_logged_without_a_log_call():
    unlogged = Branch(
        kind=BranchKind.EXCEPT,
        line=12,
        condition="OSError",
        always_raises=False,
        log_calls=(),
    )

    is_logged = unlogged.is_logged

    assert not is_logged
