import sys

import pytest

from birling.runtime import CoverageDataError, read_executed_lines


def test_read_executed_lines_returns_the_lines_that_ran_by_resolved_path(
    write_coverage_data, tmp_path, monkeypatch
):
    data_file = write_coverage_data(
        {tmp_path / "app/service.py": [1, 4, 11], "app/worker.py": [2, 3]}
    )
    monkeypatch.chdir(tmp_path)

    executed = read_executed_lines(data_file)

    assert executed == {
        (tmp_path / "app/service.py").resolve(): frozenset({1, 4, 11}),
        (tmp_path / "app/worker.py").resolve(): frozenset({2, 3}),
    }


def test_read_executed_lines_rejects_a_missing_file(tmp_path):
    data_file = tmp_path / ".coverage"

    with pytest.raises(CoverageDataError, match=r": no such file$"):
        read_executed_lines(data_file)


def test_read_executed_lines_rejects_a_file_that_is_not_coverage_data(tmp_path):
    data_file = tmp_path / ".coverage"
    data_file.write_text("[run]\nbranch = true\n")

    with pytest.raises(CoverageDataError, match=r": not coverage data$"):
        read_executed_lines(data_file)


def test_read_executed_lines_needs_the_coverage_extra(write_coverage_data, monkeypatch):
    data_file = write_coverage_data({})
    monkeypatch.setitem(sys.modules, "coverage", None)

    with pytest.raises(CoverageDataError) as raised:
        read_executed_lines(data_file)

    assert str(raised.value) == f"{data_file}: reading it needs birling[coverage]"
