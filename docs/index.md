# birling

birling measures log coverage in Python projects: how well the code is covered by log calls, whether through the standard [`logging`](https://docs.python.org/3/library/logging.html) module, [structlog](https://www.structlog.org/), [loguru](https://github.com/Delgan/loguru) or a project's own helpers, the way [coverage.py](https://coverage.readthedocs.io/) measures how well it is covered by tests.

A handled exception that leaves no log is a failure nobody hears about. birling finds the places in the code where something should be logged, checks whether a log call is there, and gives the project a score that a CI run can hold to a minimum.

By default, the places that should log are `except` handlers that do not raise again. Other kinds of branch, such as `if` and `else`, can be added in the configuration.

## Installation

birling needs Python 3.11 or later and has no dependencies of its own. It is not published on PyPI yet, so install it from a checkout of its repository:

```shell
pip install ./birling
```

To mark the gaps that ran in the tests, install the `coverage` extra, which brings in coverage.py:

```shell
pip install "./birling[coverage]"
```

## Quick start

Point the `birling` command at the project's code:

```shell
$ birling shop
Name              Branches  Logged  Score  Unlogged
---------------------------------------------------
shop/orders.py           2       1    50%  13
shop/payments.py         2       1    50%  13
---------------------------------------------------
TOTAL                    4       2    50%
```

Each row is a module with branches that should log. **Branches** counts them, **Logged** counts those that hold a log call, and **Unlogged** lists the lines of those that do not.

To fail a CI run below a score, set a minimum in `pyproject.toml`:

```toml
[tool.birling]
fail-under = 80
```

The rest of this documentation covers:

- [Usage](usage.md): the command, its report and its exit status, and the Python interface
- [Configuration](configuration.md): the `[tool.birling]` table
- [How it works](how-it-works.md): what counts as a branch, which branches should log, and how log calls are recognised
- [API reference](reference.md)

## The name

> Log rolling, sometimes called birling, is a sparring sport involving two competitors, each standing on one end of a free-floating log in a body of water. The two battle to dislodge each other from the log while keeping their own footing on it by spinning and kicking it and various other means.
>
> — Wikipedia, [Logrolling (sport)](https://en.wikipedia.org/wiki/Logrolling_%28sport%29)

The lumberjacks' sport lends its name to a tool for keeping on top of a project's logs.
