# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Unreleased changes are kept as news fragments in `release-notes/`, and collated into a dated section by towncrier at release time.

<!-- towncrier release notes start -->

## [0.1.0] - 2026-10-13

### Added

- The `birling` command, which finds the branches in a project's code that should log, checks whether each holds a log call, and reports a score for each module and in total:

  - A minimum score, `fail-under` in the configuration or `--fail-under`, below which the command exits with status 1, so that a CI run can hold to it.
  - Configuration in the `[tool.birling]` table of `pyproject.toml`: which kinds of branch should log, which exceptions never need a log, and how log calls are recognised, covering `logging`, structlog, loguru and a project's own helpers.
  - A `# birling: ignore` comment on the line that opens a branch, which accepts that branch without a log.
  - `--show-unlogged`, which lists each unlogged branch as `path:line`, with its unit and how the branch is selected.
  - `--coverage-file`, which marks the unlogged branches that ran in the tests, read from coverage.py's data; it needs the `coverage` extra.
  - A Python interface, `measure_source()` and `measure_paths()`, which the command is built on.
