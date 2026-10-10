from contextlib import suppress
import re
from textwrap import dedent

from hypothesis import given
from hypothesis import strategies as st
import pytest

from birling.config import BranchKind, Config, ConfigError

keys = st.sampled_from(
    [
        "branches",
        "level-methods",
        "logger-factories",
        "logger-modules",
        "logger-objects",
        "binding-methods",
        "helpers",
        "name-fallback",
        "module-level",
        "lambdas",
        "fail-under",
    ]
)

names = st.text() | st.sampled_from([str(kind) for kind in BranchKind])

# Any value TOML can hold, and more often the shapes the table expects, with any contents.
toml_values = (
    st.recursive(
        st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text() | st.datetimes(),
        lambda values: (
            st.lists(values, max_size=3) | st.dictionaries(st.text(), values, max_size=3)
        ),
        max_leaves=8,
    )
    | st.booleans()
    | st.lists(names, max_size=3)
    | st.dictionaries(st.text(), names, max_size=3)
)


def test_the_default_config_expects_handlers_to_log_through_the_standard_logging_names():
    config = Config()

    assert config == Config(
        branches=frozenset({BranchKind.EXCEPT}),
        level_methods={
            "debug": "debug",
            "info": "info",
            "warning": "warning",
            "warn": "warning",
            "error": "error",
            "exception": "exception",
            "critical": "critical",
            "fatal": "critical",
        },
        logger_factories=frozenset({"getLogger", "get_logger", "getChild", "LoggerAdapter"}),
        logger_modules=frozenset({"logging"}),
        logger_objects=frozenset(),
        binding_methods=frozenset({"bind", "new", "opt"}),
        helpers={},
        name_fallback=True,
        module_level=False,
        lambdas=False,
        fail_under=0,
    )


def test_from_table_builds_a_config_from_the_pyproject_table():
    table = {
        "branches": ["except", "else"],
        "level-methods": {"success": "info"},
        "logger-factories": ["Logging"],
        "logger-modules": ["pyfastlogging"],
        "logger-objects": ["loguru.logger"],
        "binding-methods": ["patch"],
        "helpers": {"log_failure": "error"},
        "name-fallback": False,
        "module-level": True,
        "lambdas": True,
        "fail-under": 80,
    }

    config = Config.from_table(table)

    assert config == Config(
        branches=frozenset({BranchKind.EXCEPT, BranchKind.ELSE}),
        level_methods={**Config().level_methods, "success": "info"},
        logger_factories=frozenset(
            {"getLogger", "get_logger", "getChild", "LoggerAdapter", "Logging"}
        ),
        logger_modules=frozenset({"logging", "pyfastlogging"}),
        logger_objects=frozenset({"loguru.logger"}),
        binding_methods=frozenset({"bind", "new", "opt", "patch"}),
        helpers={"log_failure": "error"},
        name_fallback=False,
        module_level=True,
        lambdas=True,
        fail_under=80,
    )


def test_from_table_keeps_the_defaults_for_the_keys_left_out():
    config = Config.from_table({})

    assert config == Config()


def test_from_table_replaces_the_default_kinds_of_branch():
    config = Config.from_table({"branches": ["if"]})

    assert config.branches == frozenset({BranchKind.IF})


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ({"branch": ["except"]}, "tool.birling.branch: unknown key"),
        (
            {"branches": ["except", "while", "with"]},
            "tool.birling.branches: unknown while, with; "
            "expected one of except, if, else, case, try-else, loop-else",
        ),
        ({"branches": "except"}, "tool.birling.branches: expected a list of strings"),
        (
            {"logger-modules": ["logging", 1]},
            "tool.birling.logger-modules: expected a list of strings",
        ),
        (
            {"helpers": ["log_failure"]},
            "tool.birling.helpers: expected a table of level names",
        ),
        (
            {"level-methods": {"success": 25}},
            "tool.birling.level-methods: expected a table of level names",
        ),
        ({"lambdas": "yes"}, "tool.birling.lambdas: expected true or false"),
        ({"fail-under": "80"}, "tool.birling.fail-under: expected a number from 0 to 100"),
        ({"fail-under": 120}, "tool.birling.fail-under: expected a number from 0 to 100"),
        ({"fail-under": True}, "tool.birling.fail-under: expected a number from 0 to 100"),
    ],
    ids=[
        "unknown key",
        "unknown kinds of branch",
        "names not in a list",
        "a name that is not a string",
        "levels not in a table",
        "a level that is not a string",
        "a switch that is not a boolean",
        "a score that is not a number",
        "a score over 100",
        "a score that is a boolean",
    ],
)
def test_from_table_rejects_a_value_it_cannot_read_naming_its_key(table, message):
    with pytest.raises(ConfigError, match=f"^{re.escape(message)}$"):
        Config.from_table(table)


@given(st.dictionaries(keys, toml_values, max_size=3))
def test_from_table_reads_any_table_or_rejects_it_with_a_config_error(table):
    """Never raises any other exception, whatever the table holds."""
    with suppress(ConfigError):
        Config.from_table(table)


def test_from_pyproject_reads_the_birling_table(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        dedent("""
            [project]
            name = "service"

            [tool.birling]
            branches = ["except", "case"]
            helpers = { log_failure = "error" }
        """)
    )

    config = Config.from_pyproject(pyproject)

    assert config == Config(
        branches=frozenset({BranchKind.EXCEPT, BranchKind.CASE}),
        helpers={"log_failure": "error"},
    )


def test_from_pyproject_uses_the_defaults_without_a_birling_table(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.ruff]\nline-length = 96\n")

    config = Config.from_pyproject(pyproject)

    assert config == Config()


def test_from_pyproject_rejects_a_birling_entry_that_is_not_a_table(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool]\nbirling = "on"\n')

    with pytest.raises(ConfigError, match=r"^tool\.birling: expected a table$"):
        Config.from_pyproject(pyproject)
