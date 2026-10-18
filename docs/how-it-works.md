# How it works

birling reads the code without running it. It parses each module with Python's own parser, finds the branches in each function and the log calls in each branch, and counts the branches that should log and do.

## Units

A unit is a function or method. Nested functions and the methods of nested classes are units of their own, named after where they are defined, such as `Service.run` or `outer.inner`. A log call belongs to the unit it is written in, not to the one around it.

Code outside any function belongs to no unit, unless `module-level` is on; then a module's own code is a unit named `<module>`. Code in a class body, outside its methods, is never measured.

## Branches

A branch is one of several alternative paths through a unit, which runs only when something selects it:

| Kind | The branch |
|---|---|
| `except` | An `except` or `except*` handler. |
| `if` | The body of an `if` or `elif`. |
| `else` | The `else` of an `if`. |
| `case` | A `case` of a `match`. |
| `try-else` | The `else` of a `try`, which runs when nothing was raised. |
| `loop-else` | The `else` of a `for` or `while`, which runs when the loop ends without `break`. |

The body of a loop or a `with`, a `finally` block and a conditional expression are not branches: they run every time, or are expressions rather than paths.

A log call in a statement nested in a branch belongs to that branch, and to any branch around it.

## Which branches should log

A branch should log when its kind is one of those configured in `branches`, which is only `except` by default, unless it ends by raising. A handler that raises leaves the logging to whatever handles the exception; a handler that returns, continues, breaks or carries on swallows it, and without a log nobody hears about it.

A branch counts as raising only when every path through it raises. A handler that raises on one path and returns on another, as in `if error.args: raise` followed by `return None`, should log: on the path that returns, the exception is swallowed. A way out of a branch is a `return`, or a `break` or `continue` that leaves the loop around it; an `if` with an `else`, a `try` or a `match` raises when all of its paths do.

A call to a function that always raises counts as raising, awaited or not, and returned or not, as `sys.exit()` does by raising `SystemExit`. These functions are named in [`raising-functions`](configuration.md#what-should-log), by default `sys.exit`, the built-ins `exit` and `quit`, and `assert_never` from `typing` or `typing_extensions`. A call is matched by what its name refers to where it is made, as Python resolves it: `exit()` after `from sys import exit` counts, while `quit()` after `from pygame import quit` does not, and neither does a call to a parameter or a function of the module's own that is named `quit`. A name imported from one of two places, as with a fallback import, counts when both places are named. A method of an object, such as `parser.exit()`, does not count, since the name alone cannot tell which object it is called on. A call that ends the process at once, such as `os._exit()`, does not count either: an exception carries on up the stack, where code can catch it and log, while `os._exit()` leaves nothing the chance.

## Accepting a branch without a log

Some branches rightly do not log, such as `except KeyError: return default`. There are two ways to accept them, and an accepted branch drops out of the count.

A `# noqa: BRL001` comment on the line that opens the branch accepts that branch:

```python
try:
    return cache[key]
except KeyError:  # noqa: BRL001
    return default
```

The comment takes the form linters use, so one comment can hold the codes of several tools, as in `# noqa: BLE001, BRL001`. birling reads only its own codes, written in capitals, and skips any other code as linters do, so a mistyped code leaves its finding in the report. A `# noqa` without codes accepts nothing, since on such a line it is usually meant for a linter. A project that has ruff report unknown codes in these comments (rule `RUF102`) declares birling's codes to it:

```toml
[tool.ruff.lint]
external = ["BRL"]
```

Each kind of finding has a code:

| Code | Finding |
|---|---|
| `BRL001` | A branch that should log holds no log call. |
| `BRL002` | A branch that should log holds log calls, but none of them ran in the tests. Needs [coverage data](usage.md#coverage-data). |

A branch accepted for `BRL001` drops out of the count, and so out of `BRL002` as well, which checks only the branches that should log. A branch accepted only for `BRL002` still counts.

The `ignore-exceptions` list in the [configuration](configuration.md#what-should-log) accepts every handler that catches only the exceptions it names. A bare `except` catches everything, so the list cannot accept it.

## Log calls

A call is a log call when it calls a method that logs on a logger, such as `log.warning(...)`. A method logs when its name is one of the level methods, such as `info` or `error`, or is `log`, which takes its level from its first argument.

The expression the method is called on is a logger when it is:

- a name or attribute assigned a newly created logger, such as `log = logging.getLogger(__name__)` at module level, in the function, or as `self.logger` in any method of the class
- a call that creates one, as in `logging.getLogger(__name__).info(...)`
- a logger derived from one through a binding method, as in `log.bind(user=user).info(...)`
- a logging module, as in `logging.warning(...)`, or a logger object imported from a module, such as [loguru](https://github.com/Delgan/loguru)'s `logger`
- with the name fallback on, a name that reads as a logger's, such as `logger` or `self._log`

A logging module's function imported by name, as in `from logging import warning`, is recognised when called, and so is any call to a configured helper.

What counts as a logger is set in the [configuration](configuration.md#what-counts-as-a-log-call).

## Limitations

- A logger reached through an index or a call, as in `loggers["audit"].info(...)`, is not recognised.
- A branch whose only statement is `...` or a docstring leaves nothing for [coverage.py](https://coverage.readthedocs.io/) to record, so it is never marked as having run.
- An exception swallowed by a context manager, such as `contextlib.suppress`, has no branch in the code and so cannot be measured.
