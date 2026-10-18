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
| `--coverage-file FILE` | [coverage.py](https://coverage.readthedocs.io/)'s data from a test run, to mark the unlogged branches that ran and count the logged branches where no log call ran. Needs the `coverage` extra. |
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

Only modules with at least one branch that should log get a row. The score depends on the code alone, so it is the same on every run.

## Listing the unlogged branches

With `--show-unlogged`, each unlogged branch gets a line of its own after the report, naming its unit and how the branch is selected. Editors and CI logs turn the `path:line` at its start into a link:

```text
$ birling shop --show-unlogged
...
TOTAL                    4       2    50%

shop/orders.py:12: load_order: except TimeoutError
shop/payments.py:12: charge: except ValueError
```

With `--coverage-file`, a branch that ran in the tests is marked `(ran in the tests)`.

## Exit status

| Status | Meaning |
|---|---|
| 0 | The total score is at least the minimum. |
| 1 | The total score is below the minimum. |
| 2 | The configuration, a module or the coverage data cannot be read, or the command was called wrongly. The message names the file at fault. |

The minimum is `fail-under` in the configuration, or `--fail-under`, and is 0 unless set.

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

A branch counts as having run when its first statement ran. Modules are matched to the data by their resolved paths, so data whose paths were remapped, as with `coverage combine` and its `[paths]` setting, does not match.

The data also shows the logged branches where no log call ran in the tests, so their log calls are untested: a mistake in one, such as a wrong argument, shows only when the branch runs for real. The last line of the report counts them, and `--show-unrun-logs` lists them:

```text
$ birling shop --coverage-file .coverage --show-unrun-logs
...
no log call ran in the tests: 1 of 2 logged branches in the coverage data

shop/payments.py:9: charge: except TimeoutError (no log call ran in the tests)
```

A log call counts as having run when its line ran, even if that line skipped it, as a conditional expression can. A module the data does not hold is left out of the count and the listing, since it cannot be told from one whose paths were remapped.

## From Python

The command is a thin layer over three functions:

```python
from pathlib import Path

from birling.config import Config
from birling.measurement import measure_paths
from birling.report import to_text

config = Config.from_pyproject(Path("pyproject.toml"))
measurements = measure_paths([Path("shop")], config)
print(to_text(measurements))
```

`measure_paths()` returns a `Measurement` for each module, by path. A `Measurement` lists every function and method with the branches that should log, and gives `branch_count`, `logged_count` and `score`; `Measurement.combine()` adds measurements up. `measure_source()` measures a module's source given as a string. See the [API reference](reference.md) for the details.
