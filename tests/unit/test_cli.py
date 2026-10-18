from textwrap import dedent

import pytest

from birling import __version__
from birling.cli import main

SERVICE = """
    import logging

    def load(path):
        try:
            return read(path)
        except FileNotFoundError:
            logging.warning("missing %s", path)
            return None
        except PermissionError:
            return None

    def check(value):
        if value:
            return 1
        return 0
"""


@pytest.fixture
def project(write_project, monkeypatch):
    root = write_project({"app/service.py": SERVICE})
    monkeypatch.chdir(root)
    return root


def test_main_prints_the_report_of_the_paths_given(project, capsys):
    status = main(["app"])

    assert status == 0
    assert capsys.readouterr().out == dedent("""\
        Name            Branches  Logged  Score  Unlogged
        -------------------------------------------------
        app/service.py         2       1    50%  10
        -------------------------------------------------
        TOTAL                  2       1    50%
    """)


def test_main_measures_with_the_configuration_in_pyproject(project, capsys):
    (project / "pyproject.toml").write_text('[tool.birling]\nbranches = ["except", "if"]\n')

    status = main(["app"])

    assert status == 0
    assert "TOTAL                  3       1    33%" in capsys.readouterr().out


def test_main_reads_the_configuration_from_the_file_given(project, capsys):
    (project / "birling.toml").write_text('[tool.birling]\nbranches = ["if"]\n')

    status = main(["app", "--config", "birling.toml"])

    assert status == 0
    assert "TOTAL                  1       0     0%" in capsys.readouterr().out


def test_main_fails_when_the_score_is_below_the_configured_minimum(project, capsys):
    (project / "pyproject.toml").write_text("[tool.birling]\nfail-under = 75\n")

    status = main(["app"])

    assert status == 1
    assert capsys.readouterr().err == "birling: score 50.00% is below the minimum of 75%\n"


def test_main_takes_the_minimum_score_from_the_command_line_over_the_configuration(
    project, capsys
):
    (project / "pyproject.toml").write_text("[tool.birling]\nfail-under = 75\n")

    status = main(["app", "--fail-under", "50"])

    assert status == 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    ("pyproject", "message"),
    [
        (
            "[tool.birling]\nlambda = true\n",
            "cannot read pyproject.toml: tool.birling.lambda: unknown key",
        ),
        (
            "[tool.birling\n",
            "cannot read pyproject.toml: Expected ']' at the end of a table declaration"
            " (at line 1, column 14)",
        ),
    ],
    ids=["invalid configuration", "invalid TOML"],
)
def test_main_fails_when_it_cannot_read_the_configuration(project, capsys, pyproject, message):
    (project / "pyproject.toml").write_text(pyproject)

    status = main(["app"])

    assert status == 2
    assert capsys.readouterr().err == f"birling: error: {message}\n"


def test_main_fails_when_the_configuration_file_given_is_missing(project, capsys):
    status = main(["app", "--config", "missing.toml"])

    assert status == 2
    assert capsys.readouterr().err == (
        "birling: error: cannot read missing.toml:"
        " [Errno 2] No such file or directory: 'missing.toml'\n"
    )


def test_main_fails_naming_a_module_it_cannot_parse(project, capsys):
    (project / "app/broken.py").write_text("def broken(:\n")

    status = main(["app"])

    assert status == 2
    assert capsys.readouterr().err == (
        "birling: error: cannot measure app/broken.py: invalid syntax at line 1\n"
    )


def test_main_marks_the_unlogged_branches_that_ran_from_the_coverage_data(
    project, write_coverage_data, capsys
):
    data_file = write_coverage_data({project / "app/service.py": [2, 4, 5, 6, 10, 11]})

    status = main(["app", "--coverage-file", str(data_file)])

    assert status == 0
    assert capsys.readouterr().out == dedent("""\
        Name            Branches  Logged  Score  Unlogged
        -------------------------------------------------
        app/service.py         2       1    50%  10*
        -------------------------------------------------
        TOTAL                  2       1    50%

        * ran in the tests: 1 of 1 unlogged branches
        no log call ran in the tests: 1 of 1 logged branches in the coverage data
    """)


def test_main_fails_when_it_cannot_read_the_coverage_data(project, capsys):
    status = main(["app", "--coverage-file", ".coverage"])

    assert status == 2
    assert capsys.readouterr().err == (
        "birling: error: cannot read the coverage data in .coverage: no such file\n"
    )


def test_main_lists_each_unlogged_branch_after_the_report_when_asked(project, capsys):
    status = main(["app", "--show-unlogged"])

    assert status == 0
    assert capsys.readouterr().out.endswith(
        "TOTAL                  2       1    50%\n\n"
        "app/service.py:10: BRL001 no log call: load: except PermissionError\n"
    )


def test_main_lists_nothing_when_every_branch_that_should_log_does(project, capsys):
    (project / "app/service.py").write_text("def load():\n    return None\n")

    status = main(["app", "--show-unlogged"])

    assert status == 0
    assert capsys.readouterr().out.endswith("TOTAL         0       0   100%\n")


def test_main_lists_each_logged_branch_whose_log_calls_never_ran_when_asked(
    project, write_coverage_data, capsys
):
    data_file = write_coverage_data({project / "app/service.py": [2, 4, 5, 6, 10, 11]})

    status = main(["app", "--coverage-file", str(data_file), "--show-unrun-logs"])

    assert status == 0
    assert capsys.readouterr().out.endswith(
        "logged branches in the coverage data\n\n"
        "app/service.py:7: BRL002 no log call ran in the tests: "
        "load: except FileNotFoundError\n"
    )


def test_main_rejects_listing_the_log_calls_that_never_ran_without_coverage_data(
    project, capsys
):
    with pytest.raises(SystemExit) as raised:
        main(["app", "--show-unrun-logs"])

    assert raised.value.code == 2
    assert "--show-unrun-logs needs --coverage-file" in capsys.readouterr().err


def test_main_rejects_a_call_without_paths(capsys):
    with pytest.raises(SystemExit) as raised:
        main([])

    assert raised.value.code == 2
    assert "the following arguments are required: PATH" in capsys.readouterr().err


def test_main_shows_the_version(capsys):
    with pytest.raises(SystemExit) as raised:
        main(["--version"])

    assert raised.value.code == 0
    assert capsys.readouterr().out == f"birling {__version__}\n"
