# Contributing

Issues labelled [good first issue](https://github.com/berislavlopac/birling/labels/good%20first%20issue) are small and self-contained, and [help wanted](https://github.com/berislavlopac/birling/labels/help%20wanted) marks those where outside knowledge would help most. For a larger change, open an issue first, so the approach can be agreed before the work.

## Setup

birling uses [uv](https://docs.astral.sh/uv/) for its environment and [just](https://just.systems/) to run tasks. With both installed:

```shell
uv sync
just --list
```

`uv sync` installs the development and test tools. The documentation tools are in a separate group, which `just docs` and `just docs-build` bring in themselves.

## Before a pull request

```shell
just check      # formatting, lint, type and dependency checks
just test-cov   # the tests, with a coverage report
```

`just test-all` runs the tests on every supported Python version, 3.11 to 3.15, and `just docs-build` builds the documentation the way Read the Docs does, failing on any warning. `just reformat` applies the formatting that `just check` expects.

## Code

The source is fully annotated and checked with pyrefly; the tests are not. Docstrings are in Markdown, with Google-style `Args:`, `Returns:` and `Raises:` sections, on every function, private ones included. birling has no runtime dependencies, and should keep it that way.

## Tests

Each module in `birling/` has its own test module in `tests/unit/`, which calls that module's functions directly, the way a caller would. A test's name reads as a sentence describing the behaviour, as in `test_a_handler_that_raises_need_not_log`, because `pytest --spec` prints the names as a specification. A test docstring starts with a one-line summary, followed by a blank line.

## News fragments

A change that users should hear about gets a news fragment in `release-notes/`, created with `just news <type> [issue]`. The types are described in [`release-notes/README.md`](release-notes/README.md). At the next release, the fragments become its section of the changelog.
