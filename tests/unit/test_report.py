from pathlib import Path
from textwrap import dedent

from birling.measurement import measure_source
from birling.report import to_listing, to_text


def test_to_text_lists_each_module_with_branches_that_should_log_and_the_total():
    service = dedent("""
        import logging

        def load(path):
            try:
                return read(path)
            except FileNotFoundError:
                logging.warning("missing %s", path)
                return None
            except PermissionError:
                return None
            except IsADirectoryError:
                return None
    """)
    worker = dedent("""
        import logging

        def run(job):
            try:
                job()
            except Exception:
                logging.exception("job failed")
    """)
    measurements = {
        Path("app/service.py"): measure_source(service),
        Path("app/routes.py"): measure_source("routes = []\n"),
        Path("app/jobs/worker.py"): measure_source(worker),
    }

    text = to_text(measurements)

    assert text == dedent("""\
        Name                Branches  Logged  Score  Unlogged
        -----------------------------------------------------
        app/service.py             3       1    33%  10, 12
        app/jobs/worker.py         1       1   100%
        -----------------------------------------------------
        TOTAL                      4       2    50%
    """)


def test_to_text_rounds_a_score_down_so_only_a_full_one_shows_100():
    source = dedent("""
        import logging

        def run(job):
            try:
                job()
            except ValueError:
                logging.warning("bad job")
            except Exception:
                logging.error("failed")
    """)
    logged = measure_source(source)
    partly_logged = measure_source(source.replace('logging.error("failed")', "pass"))
    measurements = {Path(f"jobs/job{number}.py"): logged for number in range(199)}
    measurements[Path("jobs/last.py")] = partly_logged

    text = to_text(measurements)

    assert text.splitlines()[-1].split() == ["TOTAL", "400", "399", "99%"]


def test_to_text_shows_a_full_score_when_no_branch_should_log():
    measurements = {Path("app/routes.py"): measure_source("routes = []\n")}

    text = to_text(measurements)

    assert text == dedent("""\
        Name   Branches  Logged  Score  Unlogged
        ----------------------------------------
        TOTAL         0       0   100%
    """)


def test_to_text_marks_the_unlogged_branches_that_ran_in_the_tests():
    source = dedent("""
        def load(path):
            try:
                return read(path)
            except FileNotFoundError:
                return None
            except PermissionError:
                return None
    """)
    module = Path("app/service.py")
    executed = {module.resolve(): frozenset({3, 4, 5, 6})}

    text = to_text({module: measure_source(source)}, executed)

    assert text == dedent("""\
        Name            Branches  Logged  Score  Unlogged
        -------------------------------------------------
        app/service.py         2       0     0%  5*, 7
        -------------------------------------------------
        TOTAL                  2       0     0%

        * ran in the tests: 1 of 2 unlogged branches
    """)


def test_to_listing_gives_a_line_for_each_branch_that_should_log_but_does_not():
    service = dedent("""
        def load(path):
            try:
                return read(path)
            except (FileNotFoundError, IsADirectoryError):
                return None

        def save(path):
            try:
                write(path)
            except:
                return False
    """)
    measurements = {
        Path("app/service.py"): measure_source(service),
        Path("app/routes.py"): measure_source("routes = []\n"),
    }

    listing = to_listing(measurements)

    assert listing == dedent("""\
        app/service.py:5: load: except (FileNotFoundError, IsADirectoryError)
        app/service.py:11: save: except
    """)


def test_to_listing_marks_the_branches_that_ran_in_the_tests():
    source = dedent("""
        def load(path):
            try:
                return read(path)
            except FileNotFoundError:
                return None
            except PermissionError:
                return None
    """)
    module = Path("app/service.py")
    executed = {module.resolve(): frozenset({3, 4, 5, 6})}

    listing = to_listing({module: measure_source(source)}, executed)

    assert listing == dedent("""\
        app/service.py:5: load: except FileNotFoundError (ran in the tests)
        app/service.py:7: load: except PermissionError
    """)


def test_to_listing_is_empty_when_every_branch_that_should_log_does():
    source = dedent("""
        import logging

        def load(path):
            try:
                return read(path)
            except OSError:
                logging.exception("cannot read %s", path)
    """)

    listing = to_listing({Path("app/service.py"): measure_source(source)})

    assert listing == ""
