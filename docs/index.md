# birling

birling measures log coverage in Python projects: how well the code is covered by log calls, the way [coverage.py](https://coverage.readthedocs.io/) measures how well it is covered by tests. It recognises the standard [`logging`](https://docs.python.org/3/library/logging.html) module, [structlog](https://www.structlog.org/) and [loguru](https://github.com/Delgan/loguru), and a project's own logging helpers.

A handled exception that leaves no log is a failure nobody hears about. birling finds the places in the code where something should be logged, checks whether a log call is there, and gives the project a score that a CI run can hold to a minimum.

The places it looks at are branches: the alternative paths through a function, such as an `except` handler or the body of an `if`. By default, the branches that should log are `except` handlers that do not raise again; other kinds of branch can be added in the configuration.

## Installation

birling needs Python 3.11 or later and has no dependencies of its own. Install it from PyPI:

```shell
pip install birling
```

To mark the gaps that ran in the tests, and find the logged branches where no log call ran, birling reads coverage.py's data, which needs coverage.py where birling runs. It is usually there already where the tests run; the `coverage` extra installs it otherwise:

```shell
pip install "birling[coverage]"
```

[uvx](https://docs.astral.sh/uv/guides/tools/) runs birling in an environment of its own, which does not see the project's, so add coverage.py to it:

```shell
uvx --with coverage birling shop --coverage-file .coverage
```

## Quick start

Point the `birling` command at the project's code:

```shell
$ birling shop
Name              Branches  Logged  Score  Unlogged
---------------------------------------------------
shop/orders.py           2       1    50%  12
shop/payments.py         2       1    50%  12
---------------------------------------------------
TOTAL                    4       2    50%
```

Each row is a module with branches that should log. **Branches** counts them, **Logged** counts those that hold a log call, and **Unlogged** lists the lines of those that do not.

To list each unlogged branch on a line of its own, which editors and CI logs turn into a link, add `--show-unlogged`:

```shell
$ birling shop --show-unlogged
...
shop/orders.py:12: BRL001 no log call: load_order: except TimeoutError
shop/payments.py:12: BRL001 no log call: charge: except ValueError
```

A branch that rightly does not log, such as `except KeyError: return default`, is accepted with a `# noqa: BRL001` comment on its `except` line, and drops out of the count.

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
