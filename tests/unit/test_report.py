from pathlib import Path
from textwrap import dedent

from birling.measurement import measure_source
from birling.report import to_listing, to_text, to_unrun_listing


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
        no log call ran in the tests: 0 of 0 logged branches in the coverage data
    """)


def test_to_text_counts_the_logged_branches_whose_log_calls_never_ran():
    """Counts them only in the modules the coverage data holds.

    A module the data does not hold cannot be told from one whose paths were remapped.
    """
    source = dedent("""
        import logging

        def load(path):
            try:
                return read(path)
            except FileNotFoundError:
                logging.warning("missing %s", path)
            except PermissionError:
                logging.warning("denied %s", path)
    """)
    held = Path("app/service.py")
    executed = {held.resolve(): frozenset({5, 6, 7, 8})}
    measurements = {held: measure_source(source), Path("app/other.py"): measure_source(source)}

    text = to_text(measurements, executed)

    assert text == dedent("""\
        Name            Branches  Logged  Score  Unlogged
        -------------------------------------------------
        app/service.py         2       2   100%
        app/other.py           2       2   100%
        -------------------------------------------------
        TOTAL                  4       4   100%

        * ran in the tests: 0 of 0 unlogged branches
        no log call ran in the tests: 1 of 2 logged branches in the coverage data
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


def test_to_text_leaves_a_branch_accepted_for_brl002_out_of_the_logged_branches_counted():
    source = dedent("""
        import logging

        def load(path):
            try:
                return read(path)
            except OSError:  # noqa: BRL002
                logging.exception("cannot read %s", path)
    """)
    module = Path("app/service.py")
    executed = {module.resolve(): frozenset({5, 6})}

    text = to_text({module: measure_source(source)}, executed)

    assert text == dedent("""\
        Name            Branches  Logged  Score  Unlogged
        -------------------------------------------------
        app/service.py         1       1   100%
        -------------------------------------------------
        TOTAL                  1       1   100%

        * ran in the tests: 0 of 0 unlogged branches
        no log call ran in the tests: 0 of 0 logged branches in the coverage data
    """)


def test_to_unrun_listing_gives_a_line_for_each_logged_branch_whose_log_calls_never_ran():
    source = dedent("""
        import logging

        def load(path):
            try:
                return read(path)
            except FileNotFoundError:
                logging.warning("missing %s", path)
            except PermissionError:
                logging.warning("denied %s", path)

        def save(path):
            try:
                write(path)
            except OSError:
                logging.exception("cannot write %s", path)
    """)
    module = Path("app/service.py")
    executed = {module.resolve(): frozenset({5, 6, 7, 8, 13, 14})}

    listing = to_unrun_listing({module: measure_source(source)}, executed)

    assert listing == dedent("""\
        app/service.py:9: load: except PermissionError (no log call ran in the tests)
        app/service.py:15: save: except OSError (no log call ran in the tests)
    """)


def test_to_unrun_listing_leaves_out_a_module_the_coverage_data_does_not_hold():
    source = dedent("""
        import logging

        def load(path):
            try:
                return read(path)
            except OSError:
                logging.exception("cannot read %s", path)
    """)
    executed = {Path("app/other.py").resolve(): frozenset({5, 6})}

    listing = to_unrun_listing({Path("app/service.py"): measure_source(source)}, executed)

    assert listing == ""


def test_to_unrun_listing_lists_a_branch_that_ran_but_left_before_its_log_call():
    source = dedent("""
        import logging

        def load(path, cache):
            try:
                return read(path)
            except OSError:
                if path in cache:
                    return cache[path]
                logging.warning("cannot read %s", path)
                return None
    """)
    module = Path("app/service.py")
    executed = {module.resolve(): frozenset({5, 6, 7, 8, 9})}

    listing = to_unrun_listing({module: measure_source(source)}, executed)

    assert listing == "app/service.py:7: load: except OSError (no log call ran in the tests)\n"


def test_to_unrun_listing_leaves_out_a_branch_where_any_of_its_log_calls_ran():
    source = dedent("""
        import logging

        def load(path, verbose):
            try:
                return read(path)
            except OSError:
                if verbose:
                    logging.debug("details of %s", path)
                logging.warning("cannot read %s", path)
    """)
    module = Path("app/service.py")
    executed = {module.resolve(): frozenset({5, 6, 7, 8, 10})}

    listing = to_unrun_listing({module: measure_source(source)}, executed)

    assert listing == ""


def test_to_unrun_listing_leaves_out_a_branch_accepted_for_brl002():
    source = dedent("""
        import logging

        def load(path):
            try:
                return read(path)
            except OSError:  # noqa: BRL002
                logging.exception("cannot read %s", path)
    """)
    module = Path("app/service.py")
    executed = {module.resolve(): frozenset({5, 6})}

    listing = to_unrun_listing({module: measure_source(source)}, executed)

    assert listing == ""
