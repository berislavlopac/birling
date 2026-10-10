# Configuration

birling reads the `[tool.birling]` table of `pyproject.toml`. Every key is optional, and a project using the standard [`logging`](https://docs.python.org/3/library/logging.html) module needs none of them.

```toml
[tool.birling]
branches = ["except", "else"]
fail-under = 80
helpers = { log_failure = "error" }
```

An unknown key or a value of the wrong type stops the command with exit status 2 and a message naming the key, such as `tool.birling.lambdas: expected true or false`.

## What should log

| Key | Default | Meaning |
|---|---|---|
| `branches` | `["except"]` | The kinds of branch that should log, unless they end by raising: any of `except`, `if`, `else`, `case`, `try-else` and `loop-else`. See [How it works](how-it-works.md#branches). Replaces the default. |
| `module-level` | `false` | Whether a module's own code, outside its functions and classes, is measured as a unit named `<module>`. Off by default, because the usual handler at module level is an optional import, such as `except ImportError:`. |
| `lambdas` | `false` | Whether a log call in a lambda counts for the code the lambda is written in. Off by default, because a lambda's body runs when the lambda is called, not where it is written. |
| `fail-under` | `0` | The lowest acceptable score, from 0 to 100. Below it, the command exits with status 1. |

## What counts as a log call

These keys describe the logging libraries a project uses. The values given add to the defaults, which cover the standard `logging` module.

| Key | Default | Meaning |
|---|---|---|
| `level-methods` | `debug`, `info`, `warning`, `warn`, `error`, `exception`, `critical`, `fatal` | Method names that log, each with the level it logs at, such as `{ success = "success" }`. The level is recorded with each log call; any name will do. |
| `logger-factories` | `getLogger`, `get_logger`, `getChild`, `LoggerAdapter` | Functions, classes and methods that create a logger. A name assigned the result of a call to one is a logger. |
| `logger-modules` | `logging` | Modules that log through functions of their own, as in `logging.warning(...)` or `from logging import warning`. |
| `logger-objects` | none | Loggers imported from a module, each written as `module.name`, such as `loguru.logger`. |
| `binding-methods` | `bind`, `new`, `opt` | Methods that return a logger derived from the one they are called on, as in `log.bind(user=user).info(...)`. |
| `helpers` | none | The project's own functions that log, each with the level it logs at, such as `{ log_failure = "error" }`. A call to a function or method of that name is a log call. |
| `name-fallback` | `true` | Whether a receiver named like a logger is taken for one: `log`, `logger`, or a name ending in `_log` or `_logger`, in any case. |

A `log` method or function is recognised as well, taking its level from its first argument, as in `log.log(logging.WARNING, ...)`.

## Logging libraries

[structlog](https://www.structlog.org/) needs no configuration: `structlog.get_logger()` is a logger factory by default.

[loguru](https://github.com/Delgan/loguru) logs through a logger object imported from the module:

```toml
[tool.birling]
logger-objects = ["loguru.logger"]
level-methods = { success = "success", trace = "trace" }
```

[pyfastlogging](https://github.com/brmmm3/fastlogging-rs) logs through its module's functions, and through loggers created with `Logging(...)`:

```toml
[tool.birling]
logger-modules = ["pyfastlogging"]
logger-factories = ["Logging"]
level-methods = { trace = "trace" }
```

A project's own logging helpers are named with their level:

```toml
[tool.birling]
helpers = { log_failure = "error", audit = "info" }
```
