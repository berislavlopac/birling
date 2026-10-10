# birling

birling measures log coverage in Python projects: how well the code is covered by log calls, whether through the standard [`logging`](https://docs.python.org/3/library/logging.html) module, [structlog](https://www.structlog.org/), [loguru](https://github.com/Delgan/loguru) or a project's own helpers, the way [coverage.py](https://coverage.readthedocs.io/) measures how well it is covered by tests.

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

birling needs Python 3.11 or later and has no dependencies of its own. It is not published on PyPI yet, so install it from a checkout:

```shell
pip install ./birling
```

The `coverage` extra, `./birling[coverage]`, adds coverage.py, which the command needs to mark the unlogged branches that ran in the tests.

## Usage

```shell
birling PATH... [--config FILE] [--fail-under SCORE] [--coverage-file FILE]
```

The command reads its configuration from the `[tool.birling]` table of `pyproject.toml`, and exits with status 1 when the score is below the minimum:

```toml
[tool.birling]
fail-under = 80
```

The standard `logging` module needs no configuration; other logging libraries and a project's own logging helpers are described in the table.

## Documentation

The documentation covers the command, the configuration, how branches and log calls are found, and the Python interface. It is in `docs/`; `just docs` serves it locally.

## The name

> Log rolling, sometimes called birling, is a sparring sport involving two competitors, each standing on one end of a free-floating log in a body of water. The two battle to dislodge each other from the log while keeping their own footing on it by spinning and kicking it and various other means.
>
> — Wikipedia, [Logrolling (sport)](https://en.wikipedia.org/wiki/Logrolling_%28sport%29)

The lumberjacks' sport lends its name to a tool for keeping on top of a project's logs.

## Status

birling is experimental: its interface may change before the first release.
