"""Reading which lines ran from coverage.py's data, which needs coverage.py installed."""

from pathlib import Path


class CoverageDataError(Exception):
    """Coverage data that cannot be read; the message names the file.

    Args:
        data_file: The data file.
        problem: What is wrong with it.
    """

    def __init__(self, data_file: Path, problem: str) -> None:
        super().__init__(f"{data_file}: {problem}")


def read_executed_lines(data_file: Path) -> dict[Path, frozenset[int]]:
    """Return the lines that ran in each module, from a coverage.py data file.

    Args:
        data_file: The data file, such as `.coverage`.

    Returns:
        The lines that ran, by the module's resolved path.

    Raises:
        CoverageDataError: When coverage.py is not installed, or the file is missing or is
            not coverage data.
    """
    try:
        from coverage import CoverageData
        from coverage.exceptions import DataError
    except ImportError as error:
        problem = (
            "coverage.py is not installed where birling runs; install birling[coverage],"
            " or run `uvx --with coverage birling`"
        )
        raise CoverageDataError(data_file, problem) from error
    if not data_file.is_file():
        raise CoverageDataError(data_file, "no such file")
    data = CoverageData(str(data_file))
    try:
        data.read()
        return {
            Path(module).resolve(): frozenset(data.lines(module) or ())
            for module in data.measured_files()
        }
    except DataError as error:
        raise CoverageDataError(data_file, "not coverage data") from error
    finally:
        data.close()
