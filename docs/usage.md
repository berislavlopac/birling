# Usage

## The command

```shell
birling PATH... [--config FILE] [--fail-under SCORE] [--coverage-file FILE] [--show-unlogged] [--show-unrun-logs]
```

The command measures the modules and directories given and prints a report. It also runs as `python -m birling`.

A directory is searched for `.py` files, skipping hidden directories and virtual environments. Only the project's own code should be measured, so pass the package's directory rather than the project's root, which would include the tests.

| Option | Meaning |
|---|---|
| `--config FILE` | The `pyproject.toml` to read the `[tool.birling]` table from. By default, `pyproject.toml` in the current directory is read if there is one. |
| `--fail-under SCORE` | Exit with status 1 when the total score is below `SCORE`, overriding `fail-under` in the configuration. |
| `--coverage-file FILE` | [coverage.py](https://coverage.readthedocs.io/)'s data from a test run, to mark the unlogged branches that ran and count the logged branches where no log call ran. Needs coverage.py where birling runs; see [Coverage data](#coverage-data). |
| `--show-unlogged` | After the report, list each unlogged branch on a line of its own. |
| `--show-unrun-logs` | After the report, list each logged branch whose log calls never ran in the tests on a line of its own. Needs `--coverage-file`. |
| `--version` | Show the version. |

## The report

```text
Name              Branches  Logged  Score  Unlogged
---------------------------------------------------
shop/orders.py           2       1    50%  12
shop/payments.py         2       1    50%  12
---------------------------------------------------
TOTAL                    4       2    50%
```

| Column | Meaning |
|---|---|
| Branches | The branches that should log. |
| Logged | Those of them that hold a log call. |
| Score | The percentage of them that do, rounded down, so 100% means every one does. A module with no branch that should log scores 100%. |
| Unlogged | The line that opens each branch that should log but does not: its `except`, `if`, `elif`, `else` or `case`. |

A branch counts as logged when it holds a log call anywhere in it, at any level, `debug` included, and also inside an `if` or a loop within it.

Only modules with at least one branch that should log get a row. The score depends on the code alone, so it is the same on every run.

## Listing the unlogged branches

With `--show-unlogged`, each unlogged branch gets a line of its own after the report: the code of the finding, `BRL001`, the function the branch is in, and what selects the branch, such as the exceptions an `except` catches. Editors and CI logs turn the `path:line` at its start into a link:

```text
$ birling shop --show-unlogged
...
TOTAL                    4       2    50%

shop/orders.py:12: BRL001 no log call: load_order: except TimeoutError
shop/payments.py:12: BRL001 no log call: charge: except ValueError
```

With `--coverage-file`, a branch that ran in the tests is marked `(ran in the tests)`.

## Exit status

| Status | Meaning |
|---|---|
| 0 | The total score is at least the minimum. |
| 1 | The total score is below the minimum. |
| 2 | The configuration, a module or the coverage data cannot be read, or the command was called wrongly. The message names the file at fault. |

The minimum is `fail-under` in the configuration, or `--fail-under`, and is 0 unless set.

## In CI

Run the command as a step of its own. To mark the gaps that ran in the tests, run it after them, on the coverage data they leave:

```shell
pytest --cov=shop
birling shop --coverage-file .coverage --show-unlogged
```

With `fail-under` set in `pyproject.toml`, the step fails when the score drops below it, and the listing gives a link to each gap in the CI log. The coverage data does not change the score, so the step passes or fails the same way with or without it.

## Coverage data

An unlogged branch that ran in the tests is a gap known to be reachable, so it is a good place to start. To find these, run the tests under coverage.py, then pass its data file to the command:

```shell
$ coverage run --source=shop -m pytest
$ birling shop --coverage-file .coverage
Name              Branches  Logged  Score  Unlogged
---------------------------------------------------
shop/orders.py           2       1    50%  12*
shop/payments.py         2       1    50%  12
---------------------------------------------------
TOTAL                    4       2    50%

* ran in the tests: 1 of 2 unlogged branches
no log call ran in the tests: 1 of 2 logged branches in the coverage data
```

With [pytest-cov](https://pytest-cov.readthedocs.io/), `pytest --cov=shop` writes the same `.coverage` file. The data does not change the score.

Reading the data needs coverage.py where birling runs. When birling is installed alongside the tests, as a development dependency, coverage.py is usually there already. `uvx` and `pipx` run birling in an environment of their own, which does not see the project's: add coverage.py to it with `uvx --with coverage birling ...`, or install `birling[coverage]` there.

A branch counts as having run when its first statement ran. birling finds a module in the data by its full path on disk, so the data has to come from a test run in the same checkout. Data combined from runs elsewhere, through coverage.py's `[paths]` setting, records other paths and is not matched.

The data also shows the logged branches where no log call ran in the tests, so their log calls are untested: a mistake in one, such as a wrong argument, shows only when the branch runs for real. The last line of the report counts them, and `--show-unrun-logs` lists them:

```text
$ birling shop --coverage-file .coverage --show-unrun-logs
...
no log call ran in the tests: 1 of 2 logged branches in the coverage data

shop/payments.py:9: BRL002 no log call ran in the tests: charge: except TimeoutError
```

A log call counts as having run when its line ran. The data records lines, not calls, so `log.warning(...) if retry else None` counts as run even when the condition skipped the call.

A `# noqa: BRL002` comment on the line that opens a branch leaves it out of this check, as described in [accepting a branch without a log](how-it-works.md#accepting-a-branch-without-a-log). A module missing from the data is left out of the count and the listing: birling cannot tell a module that never ran from one recorded under another path.

## From Python

The command is a thin layer over a few functions:

```python
from pathlib import Path

from birling.config import Config
from birling.measurement import measure_paths
from birling.report import to_listing, to_text, to_unrun_listing
from birling.runtime import read_executed_lines

config = Config.from_pyproject(Path("pyproject.toml"))
measurements = measure_paths([Path("shop")], config)
executed = read_executed_lines(Path(".coverage"))
print(to_text(measurements, executed))
print(to_listing(measurements, executed))
print(to_unrun_listing(measurements, executed))
```

`read_executed_lines()` reads the coverage data, and needs coverage.py installed. Without it, `to_text()` and `to_listing()` take the measurements alone; `to_unrun_listing()` always needs the data.

`measure_paths()` returns a `Measurement` for each module, by path. A `Measurement` lists every function and method with the branches that should log, and gives `branch_count`, `logged_count` and `score`; `Measurement.combine()` adds measurements up. `measure_source()` measures a module's source given as a string. See the [API reference](reference.md) for the details.
