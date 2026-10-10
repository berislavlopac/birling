from textwrap import dedent

import pytest
from coverage import CoverageData


@pytest.fixture
def write_project(tmp_path):
    """Return a function that writes modules, by path, into a new project directory."""

    def write(modules):
        for name, source in modules.items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(dedent(source))
        return tmp_path

    return write


@pytest.fixture
def write_coverage_data(tmp_path):
    """Return a function that writes coverage.py data of the lines that ran, by module."""

    def write(executed):
        data_file = tmp_path / ".coverage"
        data = CoverageData(str(data_file))
        data.add_lines({str(path): sorted(lines) for path, lines in executed.items()})
        data.write()
        data.close()
        return data_file

    return write
