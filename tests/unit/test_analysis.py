from textwrap import dedent, indent

import pytest

from birling.analysis import (
    MODULE_UNIT_NAME,
    Branch,
    FindingKind,
    Unit,
    collect_units,
)
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

    units = collect_units(source, Config())

    assert units == (
        Unit(
            name="handle",
            line=5,
            branches=(
                Branch(
                    kind=BranchKind.IF,
                    line=6,
                    body_line=7,
                    condition="not request",
                    exceptions=(),
                    always_raises=False,
                    log_calls=(LogCall(line=7, level="warning"),),
                ),
                Branch(
                    kind=BranchKind.EXCEPT,
                    line=11,
                    body_line=12,
                    condition="TimeoutError",
                    exceptions=("TimeoutError",),
                    always_raises=False,
                    log_calls=(),
                ),
                Branch(
                    kind=BranchKind.EXCEPT,
                    line=13,
                    body_line=14,
                    condition="ValueError",
                    exceptions=("ValueError",),
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
    source = "def run():\n" + indent(body, "    ")

    [run] = collect_units(source, Config())

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
    source = "def run():\n" + indent(body, "    ")

    [run] = collect_units(source, Config())

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
        ("sys.exit(1)", True),
        ("exit()", True),
        ("quit()", True),
        ("assert_never(error)", True),
        ("return assert_never(error)", True),
        ("parser.exit(2, 'failed')", False),
        ("server.quit()\nreturn False", False),
        ("os._exit(1)", False),
        ("log.error('failed')", False),
        ("status = sys.exit", False),
        ("if error.args:\n    sys.exit(1)\nreturn None", False),
        ("if error.args:\n    sys.exit(1)\nraise", True),
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
    source = (
        "import sys\n"
        "from typing import assert_never\n"
        "def run(items):\n"
        "    for item in items:\n"
        "        try:\n"
        "            start(item)\n"
        "        except OSError as error:\n" + indent(handler, " " * 12)
    )

    run, *_nested = collect_units(source, Config())

    handler_branch = run.branches[0]
    assert handler_branch.always_raises is always_raises


def test_a_call_raises_when_it_reaches_a_configured_raising_function_through_the_imports():
    """A dotted name is reached through the module's imports, under an alias too.

    A plain name stands for a built-in, unless an import binds it to something else.
    """
    source = dedent("""
        import sys as system
        from flask import abort
        from pygame import quit
        from sys import exit as leave

        def handle(request):
            try:
                return respond(request)
            except LookupError:
                abort(404)
            except OSError:
                system.exit(1)
            except ValueError:
                leave(1)
            except RuntimeError:
                quit()
    """)
    config = Config(raising_functions=frozenset({"flask.abort", "sys.exit", "quit"}))

    [handle] = collect_units(source, config)

    assert [branch.always_raises for branch in handle.branches] == [True, True, True, False]


def test_a_name_bound_in_the_code_hides_a_raising_function_of_the_same_name():
    """A parameter, a function of the module's own and an assignment all hide one."""
    source = dedent("""
        import sys

        def exit(code):
            print(code)

        def run(quit):
            try:
                work()
            except OSError:
                quit()
            except ValueError:
                exit(1)

        def stop():
            sys = load_settings()
            try:
                work()
            except OSError:
                sys.exit(1)
    """)

    units = collect_units(source, Config())

    assert {unit.name: [b.always_raises for b in unit.branches] for unit in units} == {
        "exit": [],
        "run": [False, False],
        "stop": [False],
    }


def test_a_name_is_resolved_in_the_scope_that_calls_it():
    """An import in one function binds the name for it and for the functions nested in it.

    A class body binds names for itself, not for its methods, as in Python.
    """
    source = dedent("""
        from sys import exit

        def setup():
            from mylib import exit
            try:
                work()
            except OSError:
                exit(1)

        def run():
            try:
                work()
            except OSError:
                exit(1)

        def main():
            from sys import exit as leave

            def stop():
                try:
                    work()
                except OSError:
                    leave(1)

        class Service:
            exit = print

            def stop(self):
                try:
                    work()
                except OSError:
                    exit(1)

        def collect(items):
            names = [exit for exit in items]
            try:
                work()
            except OSError:
                exit(1)
    """)

    units = collect_units(source, Config())

    assert {unit.name: [b.always_raises for b in unit.branches] for unit in units} == {
        "setup": [False],
        "run": [True],
        "main": [],
        "main.stop": [True],
        "Service.stop": [True],
        "collect": [True],
    }


@pytest.mark.parametrize(
    "imports",
    [
        "try:\n"
        "    from typing import assert_never\n"
        "except ImportError:\n"
        "    from typing_extensions import assert_never\n",
        "if sys.version_info >= (3, 11):\n"
        "    from typing import assert_never\n"
        "else:\n"
        "    from typing_extensions import assert_never\n",
    ],
    ids=["try", "if"],
)
def test_a_name_imported_from_either_of_two_raising_functions_raises(imports):
    source = imports + dedent("""
        def run(value):
            try:
                check(value)
            except ValueError:
                assert_never(value)
    """)

    [run] = collect_units(source, Config())

    assert run.branches[0].always_raises is True


def test_a_name_imported_from_a_raising_and_a_returning_function_does_not_raise():
    source = dedent("""
        try:
            from sys import exit
        except ImportError:
            from mylib import exit

        def run():
            try:
                work()
            except OSError:
                exit(1)
    """)

    [run] = collect_units(source, Config())

    assert run.branches[0].always_raises is False


def test_a_built_in_raising_function_is_reached_through_the_builtins_module_too():
    source = dedent("""
        import builtins
        from builtins import quit as stop

        def run():
            try:
                work()
            except OSError:
                builtins.exit(1)
            except ValueError:
                stop()
    """)

    [run] = collect_units(source, Config())

    assert [branch.always_raises for branch in run.branches] == [True, True]


def test_an_awaited_call_to_a_raising_function_raises():
    source = dedent("""
        from app.errors import fail

        async def handle(request):
            try:
                return await respond(request)
            except LookupError:
                await fail(404)
    """)
    config = Config(raising_functions=frozenset({"app.errors.fail"}))

    [handle] = collect_units(source, config)

    assert handle.branches[0].always_raises is True


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

    [check] = collect_units(source, Config())

    assert [(b.kind, b.line, b.body_line, b.condition) for b in check.branches] == [
        (BranchKind.IF, 3, 4, "value == 1"),
        (BranchKind.IF, 5, 6, "value == 2"),
        (BranchKind.ELSE, 7, 8, ""),
        (BranchKind.IF, 8, 9, "value == 3"),
    ]


def test_a_branch_opens_on_its_if_case_except_or_else_line():
    """The `else:` line comes from the tokens; the `else` of an expression is not one."""
    source = dedent("""
        def run(items, value):
            for item in items:
                start(item)
            else:

                # nothing was found
                stop(item if item else value)
            try:
                return items[0]
            except (
                IndexError
            ):
                return None
            else: done()
            match value:
                case (
                    1
                ):
                    pass
    """)

    [run] = collect_units(source, Config())

    assert [(b.kind, b.line, b.body_line) for b in run.branches] == [
        (BranchKind.LOOP_ELSE, 5, 8),
        (BranchKind.EXCEPT, 11, 14),
        (BranchKind.TRY_ELSE, 15, 15),
        (BranchKind.CASE, 18, 20),
    ]


def test_a_branch_accepts_the_codes_of_a_noqa_comment_on_the_line_that_opens_it():
    source = dedent("""
        def load(path, cache):
            try:
                return read(path)
            except KeyError:  # noqa: BRL001
                return None
            except OSError:
                return None  # noqa: BRL001
            else:  # noqa: BRL002
                cache.add(path)
    """)

    [load] = collect_units(source, Config())

    assert [(b.kind, b.ignored) for b in load.branches] == [
        (BranchKind.EXCEPT, frozenset({FindingKind.UNLOGGED})),
        (BranchKind.EXCEPT, frozenset()),
        (BranchKind.TRY_ELSE, frozenset({FindingKind.UNRUN_LOG})),
    ]


@pytest.mark.parametrize(
    ("comment", "ignored"),
    [
        ("# noqa: BRL001, BRL002", {FindingKind.UNLOGGED, FindingKind.UNRUN_LOG}),
        ("# NOQA:BLE001,BRL002", {FindingKind.UNRUN_LOG}),
        ("# noqa: BLE001", set()),
        ("# noqa: BRL009, BRLX01", set()),
        ("# noqa: brl001", set()),
        ("# noqa", set()),
    ],
    ids=[
        "codes",
        "other tools' codes",
        "only other tools' codes",
        "unknown codes",
        "lowercase code",
        "no codes",
    ],
)
def test_a_noqa_comment_accepts_only_the_kinds_of_finding_whose_codes_it_lists(
    comment, ignored
):
    source = dedent(f"""
        def load(path):
            try:
                return read(path)
            except Exception:  {comment}
                return None
    """)

    [load] = collect_units(source, Config())

    assert load.branches[0].ignored == ignored


@pytest.mark.parametrize(
    ("caught", "exceptions"),
    [
        ("KeyError", ("KeyError",)),
        ("(KeyError, requests.Timeout)", ("KeyError", "requests.Timeout")),
        ("errors()", ("errors()",)),
        ("", ()),
    ],
)
def test_a_handler_lists_the_exceptions_it_catches_as_written(caught, exceptions):
    source = dedent(f"""
        def load(path):
            try:
                read(path)
            except {caught}:
                pass
    """)

    [load] = collect_units(source, Config())

    assert [branch.exceptions for branch in load.branches] == [exceptions]


def test_a_case_is_selected_by_its_pattern_and_guard():
    source = dedent("""
        def check(value):
            match value:
                case [first, *_] if first:
                    return first
                case _:
                    return None
    """)

    [check] = collect_units(source, Config())

    assert [branch.condition for branch in check.branches] == ["[first, *_] if first", "_"]


def test_a_bare_handler_has_no_condition():
    source = dedent("""
        def load(path):
            try:
                return read(path)
            except:
                return None
    """)

    [load] = collect_units(source, Config())

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

    [load] = collect_units(source, Config())

    assert [(branch.kind, branch.line) for branch in load.branches] == [
        (BranchKind.EXCEPT, 5),
        (BranchKind.IF, 6),
        (BranchKind.EXCEPT, 9),
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

    [load] = collect_units(source, Config())

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

    [load] = collect_units(source, Config())

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

    [load] = collect_units(source, Config(lambdas=True))

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

    units = collect_units(source, Config(name_fallback=False))

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

    units = collect_units(source, Config(name_fallback=False))

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

    units = collect_units(source, Config())

    assert [(unit.name, unit.line) for unit in units] == [("run", 5), ("run", 8)]


def test_module_level_code_is_not_part_of_a_unit_by_default():
    source = dedent("""
        try:
            import fast_json as json
        except ImportError:
            import json
    """)

    units = collect_units(source, Config())

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

    units = collect_units(source, Config(module_level=True))

    assert [unit.name for unit in units] == [MODULE_UNIT_NAME, "load"]
    assert units[0] == Unit(
        name="<module>",
        line=1,
        branches=(
            Branch(
                kind=BranchKind.EXCEPT,
                line=7,
                body_line=8,
                condition="ImportError",
                exceptions=("ImportError",),
                always_raises=False,
                log_calls=(LogCall(line=8, level="info"),),
            ),
        ),
        log_calls=(LogCall(line=8, level="info"),),
    )


def test_a_branch_is_logged_when_it_holds_a_log_call():
    logged = Branch(
        kind=BranchKind.EXCEPT,
        line=11,
        body_line=12,
        condition="OSError",
        exceptions=("OSError",),
        always_raises=False,
        log_calls=(LogCall(line=12, level="warning"),),
    )

    is_logged = logged.is_logged

    assert is_logged


def test_a_branch_is_not_logged_without_a_log_call():
    unlogged = Branch(
        kind=BranchKind.EXCEPT,
        line=11,
        body_line=12,
        condition="OSError",
        exceptions=("OSError",),
        always_raises=False,
        log_calls=(),
    )

    is_logged = unlogged.is_logged

    assert not is_logged
