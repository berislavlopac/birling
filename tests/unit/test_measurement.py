import sysconfig
import warnings
from pathlib import Path
from textwrap import dedent

import pytest

from birling.analysis import Branch, Unit
from birling.config import BranchKind, Config
from birling.measurement import (
    Measurement,
    MeasurementError,
    UnitMeasurement,
    measure_paths,
    measure_source,
)
from birling.recognition import LogCall


def test_measure_source_keeps_the_branches_that_should_log_for_each_unit():
    source = dedent("""
        import logging
        log = logging.getLogger(__name__)

        def handle(request):
            try:
                return process(request)
            except TimeoutError:
                return "timeout"
            except ConnectionError:
                log.warning("connection lost")
                return "retry"
            except ValueError:
                raise
    """)
    timeout = Branch(
        kind=BranchKind.EXCEPT,
        line=8,
        body_line=9,
        condition="TimeoutError",
        exceptions=("TimeoutError",),
        always_raises=False,
        log_calls=(),
    )
    connection = Branch(
        kind=BranchKind.EXCEPT,
        line=10,
        body_line=11,
        condition="ConnectionError",
        exceptions=("ConnectionError",),
        always_raises=False,
        log_calls=(LogCall(line=11, level="warning"),),
    )
    value = Branch(
        kind=BranchKind.EXCEPT,
        line=13,
        body_line=14,
        condition="ValueError",
        exceptions=("ValueError",),
        always_raises=True,
        log_calls=(),
    )

    measurement = measure_source(source, Config())

    assert measurement == Measurement(
        units=(
            UnitMeasurement(
                unit=Unit(
                    name="handle",
                    line=5,
                    branches=(timeout, connection, value),
                    log_calls=(LogCall(line=11, level="warning"),),
                ),
                branches=(timeout, connection),
            ),
        )
    )


def test_measure_source_uses_the_default_config_when_given_none():
    source = dedent("""
        def load(path):
            if path:
                return read(path)
            try:
                return read("default")
            except OSError:
                return None
    """)

    measurement = measure_source(source)

    assert measurement == measure_source(source, Config())


@pytest.mark.parametrize("statement", ["raise", "raise RuntimeError('failed') from error"])
def test_a_handler_that_raises_need_not_log(statement):
    """Raising leaves the logging to whatever handles the exception."""
    source = dedent(f"""
        def load(path):
            try:
                return read(path)
            except OSError as error:
                {statement}
    """)

    measurement = measure_source(source)

    assert measurement.branch_count == 0


@pytest.mark.parametrize("statement", ["return None", "continue", "break", "cleanup()"])
def test_a_handler_that_ends_without_raising_should_log(statement):
    source = dedent(f"""
        def load_all(paths):
            for path in paths:
                try:
                    read(path)
                except OSError:
                    {statement}
    """)

    measurement = measure_source(source)

    assert measurement.branch_count == 1


def test_a_handler_that_raises_on_only_some_paths_should_log():
    """On the path that returns, the exception is swallowed and nothing else will log it."""
    source = dedent("""
        def load(path):
            try:
                return read(path)
            except OSError as error:
                if error.errno is None:
                    raise
                return None
    """)

    measurement = measure_source(source)

    assert measurement.branch_count == 1


def test_a_branch_accepted_by_an_ignore_comment_need_not_log():
    source = dedent("""
        def lookup(cache, key):
            try:
                return cache[key]
            except LookupError:  # birling: ignore
                return None
    """)

    measurement = measure_source(source)

    assert measurement.branch_count == 0


@pytest.mark.parametrize(
    "caught", ["KeyError", "builtins.KeyError", "(KeyError, asyncio.CancelledError)"]
)
def test_a_handler_catching_only_ignored_exceptions_need_not_log(caught):
    """Names are matched by their last part, in the handler and in the configuration."""
    source = dedent(f"""
        def lookup(cache, key):
            try:
                return cache[key]
            except {caught}:
                return None
    """)
    config = Config(ignore_exceptions=frozenset({"KeyError", "asyncio.CancelledError"}))

    measurement = measure_source(source, config)

    assert measurement.branch_count == 0


@pytest.mark.parametrize("caught", ["(KeyError, ValueError)", "Exception", ""])
def test_a_handler_catching_any_other_exception_should_log(caught):
    """A bare `except` catches everything, so no list can accept it."""
    source = dedent(f"""
        def lookup(cache, key):
            try:
                return cache[key]
            except {caught}:
                return None
    """)
    config = Config(ignore_exceptions=frozenset({"KeyError"}))

    measurement = measure_source(source, config)

    assert measurement.branch_count == 1


def test_other_kinds_of_branch_need_not_log_by_default():
    source = dedent("""
        def check(value):
            if value:
                return 1
            else:
                return 2
    """)

    measurement = measure_source(source)

    assert measurement.branch_count == 0


def test_the_configured_kinds_of_branch_should_log():
    source = dedent("""
        def check(value):
            if value:
                return 1
            else:
                return 2
    """)
    config = Config(branches=frozenset({BranchKind.IF, BranchKind.ELSE}))

    measurement = measure_source(source, config)

    [check] = measurement.units
    assert [branch.kind for branch in check.branches] == [BranchKind.IF, BranchKind.ELSE]


def test_the_score_is_the_percentage_of_branches_that_should_log_and_do():
    source = dedent("""
        import logging

        def load(path):
            try:
                return read(path)
            except FileNotFoundError:
                logging.warning("missing %s", path)
                return None
            except PermissionError:
                return None

        def save(path):
            try:
                write(path)
            except OSError:
                logging.error("cannot write %s", path)
    """)

    measurement = measure_source(source)

    assert (measurement.branch_count, measurement.logged_count) == (3, 2)
    assert measurement.score == pytest.approx(200 / 3)


def test_the_score_is_full_when_no_branch_should_log():
    source = dedent("""
        try:
            import fast_json as json
        except ImportError:
            import json

        def load(path):
            return json.loads(read(path))
    """)

    measurement = measure_source(source)

    assert (measurement.branch_count, measurement.score) == (0, 100)


def test_a_unit_measurement_lists_the_branches_that_should_log_but_do_not():
    unlogged = Branch(
        kind=BranchKind.EXCEPT,
        line=3,
        body_line=4,
        condition="TimeoutError",
        exceptions=("TimeoutError",),
        always_raises=False,
        log_calls=(),
    )
    logged = Branch(
        kind=BranchKind.EXCEPT,
        line=5,
        body_line=6,
        condition="ConnectionError",
        exceptions=("ConnectionError",),
        always_raises=False,
        log_calls=(LogCall(line=6, level="warning"),),
    )
    unit = Unit(name="handle", line=1, branches=(unlogged, logged), log_calls=logged.log_calls)
    unit_measurement = UnitMeasurement(unit=unit, branches=(unlogged, logged))

    branches = unit_measurement.unlogged

    assert branches == (unlogged,)


def test_measure_paths_measures_every_module_of_the_standard_library():
    """Every unit measured holds together, whatever the code.

    The standard library stands in for generated code: it is valid Python, uses every kind
    of branch, and looks like the code that gets measured.
    """
    config = Config(branches=frozenset(BranchKind), module_level=True, lambdas=True)
    stdlib = Path(sysconfig.get_path("stdlib"))

    measurements = measure_paths([stdlib], config)

    inconsistent = [
        (path, measured.unit.name)
        for path, measurement in measurements.items()
        for measured in measurement.units
        if not _is_consistent(measured)
    ]
    assert stdlib / "logging" / "__init__.py" in measurements
    assert inconsistent == []


def _is_consistent(measured):
    unit = measured.unit
    lines = [branch.line for branch in unit.branches]
    return (
        set(measured.branches) <= set(unit.branches)
        and lines == sorted(lines)
        and all(line >= unit.line for line in lines)
        and all(set(branch.log_calls) <= set(unit.log_calls) for branch in unit.branches)
    )


def test_measure_source_keeps_quiet_about_warnings_in_the_measured_code():
    """A warning such as an invalid escape is for the measured project's own tools."""
    source = dedent("""
        def match(text):
            return re.match("\\d+", text)
    """)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        measurement = measure_source(source)

    assert measurement.branch_count == 0


def test_measure_paths_measures_each_module_under_a_directory(write_project):
    service = """
        def load(path):
            try:
                return read(path)
            except OSError:
                return None
    """
    root = write_project({"app/service.py": service, "app/api/routes.py": "routes = []\n"})

    measurements = measure_paths([root / "app"])

    assert measurements == {
        root / "app/api/routes.py": Measurement(units=()),
        root / "app/service.py": measure_source(dedent(service)),
    }


def test_measure_paths_skips_hidden_directories_virtual_environments_and_other_files(
    write_project,
):
    root = write_project(
        {
            "app/service.py": "",
            "app/.cache/cached.py": "",
            "app/venv/pyvenv.cfg": "home = /usr/bin\n",
            "app/venv/lib/installed.py": "",
            "app/README.md": "",
            "app/types.pyi": "",
        }
    )

    measurements = measure_paths([root / "app"])

    assert list(measurements) == [root / "app/service.py"]


def test_measure_paths_measures_a_module_given_directly_and_under_a_directory_once(
    write_project,
):
    root = write_project({"app/service.py": "", "app/worker.py": ""})

    measurements = measure_paths([root / "app/worker.py", root / "app"])

    assert list(measurements) == [root / "app/service.py", root / "app/worker.py"]


def test_measure_paths_uses_the_configuration_given(write_project):
    root = write_project({"app/service.py": "def check(value):\n    if value:\n        go()\n"})
    config = Config(branches=frozenset({BranchKind.IF}))

    measurements = measure_paths([root / "app"], config)

    assert measurements[root / "app/service.py"].branch_count == 1


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        (b"def broken(:\n", "invalid syntax at line 1"),
        (b"import json\n\nname = '\xe9'\n", "not valid utf-8: invalid continuation byte"),
        (b"# -*- coding: klingon -*-\nname = 1\n", "unknown encoding: klingon"),
    ],
    ids=["invalid syntax", "undecodable bytes", "unknown encoding"],
)
def test_measure_paths_names_a_module_it_cannot_read_and_why(write_project, content, problem):
    root = write_project({"app/service.py": ""})
    module = root / "app/legacy.py"
    module.write_bytes(content)

    with pytest.raises(MeasurementError) as raised:
        measure_paths([root / "app"])

    assert str(raised.value) == f"{module}: {problem}"


def test_measure_paths_names_a_path_that_does_not_exist(tmp_path):
    missing = tmp_path / "missing.py"

    with pytest.raises(MeasurementError) as raised:
        measure_paths([missing])

    assert str(raised.value) == f"{missing}: No such file or directory"


def test_measure_paths_names_a_directory_it_cannot_search(write_project):
    root = write_project({"app/private/secret.py": ""})
    private = root / "app/private"
    private.chmod(0)

    try:
        with pytest.raises(MeasurementError) as raised:
            measure_paths([root / "app"])
    finally:
        private.chmod(0o700)

    assert str(raised.value) == f"{private}: Permission denied"


def test_measure_paths_names_the_module_when_the_analysis_itself_fails(
    write_project, monkeypatch
):
    """A failure that is a bug in the analysis keeps its traceback, with the module noted."""
    root = write_project({"app/service.py": ""})

    def fail(module, config):
        raise RecursionError

    monkeypatch.setattr("birling.measurement.collect_units", fail)

    with pytest.raises(RecursionError) as raised:
        measure_paths([root / "app"])

    assert raised.value.__notes__ == [f"while measuring {root / 'app/service.py'}"]


def test_measurements_combine_into_one_of_all_their_units():
    load = UnitMeasurement(
        unit=Unit(name="load", line=1, branches=(), log_calls=()), branches=()
    )
    save = UnitMeasurement(
        unit=Unit(name="save", line=1, branches=(), log_calls=()), branches=()
    )

    combined = Measurement.combine([Measurement(units=(load,)), Measurement(units=(save,))])

    assert combined == Measurement(units=(load, save))
