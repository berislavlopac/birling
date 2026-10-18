# birling

birling measures log coverage in Python projects: how well the code is covered by log calls, the way [coverage.py](https://coverage.readthedocs.io/) measures how well it is covered by tests. It recognises the standard [`logging`](https://docs.python.org/3/library/logging.html) module, [structlog](https://www.structlog.org/) and [loguru](https://github.com/Delgan/loguru), and a project's own logging helpers.

A handled exception that leaves no log is a failure nobody hears about. birling finds the places in the code where something should be logged, checks whether a log call is there, and gives the project a score that a CI run can hold to a minimum. By default, those places are `except` handlers that do not raise again.

```shell
$ birling shop
Name              Branches  Logged  Score  Unlogged
---------------------------------------------------
shop/orders.py           2       1    50%  12
shop/payments.py         2       1    50%  12
---------------------------------------------------
TOTAL                    4       2    50%
```

## Installation

birling needs Python 3.11 or later and has no dependencies of its own. Install it from PyPI:

```shell
pip install birling
```

To mark the unlogged branches that ran in the tests, and to find the logged branches where no log call ran, the command reads coverage.py's data, which needs coverage.py where birling runs. It is usually there already where the tests run; the `coverage` extra, `birling[coverage]`, installs it otherwise.

## Usage

```shell
birling PATH... [--config FILE] [--fail-under SCORE] [--coverage-file FILE] [--show-unlogged] [--show-unrun-logs]
```

The command reads its configuration from the `[tool.birling]` table of `pyproject.toml`, and exits with status 1 when the score is below the minimum:

```toml
[tool.birling]
fail-under = 80
```

The standard `logging` module needs no configuration; other logging libraries and a project's own logging helpers are described in the table.

`--show-unlogged` lists each unlogged branch as `path:line`, and a `# noqa: BRL001` comment on its `except` line accepts a branch that rightly does not log.

## Documentation

The documentation is at [birling.readthedocs.io](https://birling.readthedocs.io): the command, the configuration, how branches and log calls are found, and the Python interface.

## The name

> Log rolling, sometimes called birling, is a sparring sport involving two competitors, each standing on one end of a free-floating log in a body of water. The two battle to dislodge each other from the log while keeping their own footing on it by spinning and kicking it and various other means.
>
> — Wikipedia, [Logrolling (sport)](https://en.wikipedia.org/wiki/Logrolling_%28sport%29)

The lumberjacks' sport lends its name to a tool for keeping on top of a project's logs.

## Status

birling is in alpha: its interface may change from one release to the next.
