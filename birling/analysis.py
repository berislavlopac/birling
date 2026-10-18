"""Finding the units of a module, with their branches and log calls."""

import ast
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from itertools import chain
from typing import NamedTuple, Self

from birling.config import BranchKind, Config
from birling.recognition import (
    LogCall,
    LoggerScope,
    find_loggers,
    find_module_scope,
    recognise,
)
from birling.syntax import (
    Layout,
    find_bindings,
    parse,
    to_dotted_name,
    to_layout,
    walk_scope,
)

MODULE_UNIT_NAME = "<module>"
"""The name of the unit that holds a module's own code, as Python names its code object."""

# The kinds of branch opened by an `else:`, whose line the syntax tree does not record.
_ELSE_KINDS = frozenset({BranchKind.ELSE, BranchKind.TRY_ELSE, BranchKind.LOOP_ELSE})

# A noqa comment with a list of codes, as linters read it: the keyword in any case, the
# codes in capitals.
_NOQA_COMMENT = re.compile(
    r"#\s*(?i:noqa)\s*:\s*(?P<codes>[A-Z]+[0-9]+(?:[\s,]+[A-Z]+[0-9]+)*)"
)


class FindingKind(StrEnum):
    """A kind of finding, by the code that names it in reports and `# noqa` comments."""

    UNLOGGED = "BRL001"
    """A branch that should log holds no log call."""

    UNRUN_LOG = "BRL002"
    """A branch that should log holds log calls, but none of them ran in the tests."""


@dataclass(frozen=True)
class Branch:
    """One of several alternative paths through a unit."""

    kind: BranchKind
    """The construct the branch belongs to."""

    line: int
    """The line that opens the branch: its `if`, `elif`, `else`, `case` or `except`."""

    body_line: int
    """The line of the branch's first statement, the one a coverage tool records as run."""

    condition: str
    """The source of what selects the branch: a condition, exception types or a pattern.

    Empty for an `else` and for a bare `except`.
    """

    exceptions: tuple[str, ...]
    """The exception types an `except` handler catches, as written.

    Empty for other kinds of branch and for a bare `except`.
    """

    always_raises: bool
    """Whether every path through the branch ends by raising.

    A call to one of the configured functions that always raise counts as raising.
    """

    log_calls: tuple[LogCall, ...]
    """The log calls in the branch, those in its nested statements included.

    Those in lambdas are included only when the configuration says so.
    """

    ignored: frozenset[FindingKind] = frozenset()
    """The kinds of finding accepted by a `# noqa` comment on the line that opens the branch."""

    @property
    def is_logged(self) -> bool:
        """Whether the branch holds a log call."""
        return bool(self.log_calls)


@dataclass(frozen=True)
class Unit:
    """A function or method, or a module's own code."""

    name: str
    """The qualified name, such as `Service.run` or `outer.inner`."""

    line: int
    """The line of the `def`, or 1 for a module's own code."""

    branches: tuple[Branch, ...]
    """The unit's branches, in the order of their lines."""

    log_calls: tuple[LogCall, ...]
    """The log calls in the unit, without those in nested functions and classes.

    Those in lambdas are included only when the configuration says so.
    """


def collect_units(source: str, config: Config) -> tuple[Unit, ...]:
    """Return the functions and methods of a module, nested ones included.

    The module's own code, outside its functions and classes, is a unit named `<module>`
    when the configuration says so.

    Args:
        source: The module's source.
        config: What counts as a log call, and whether module-level code counts.

    Returns:
        The units, each one before those nested in it.
    """
    module = parse(source)
    functions = config.raising_functions
    builtins = frozenset(function for function in functions if "." not in function)
    names = _Names(find_module_scope(module, config), builtins, functions)
    names = names.with_bindings(find_bindings(walk_scope(module.body)))
    scan = _scan(module.body, config)
    units = _collect(scan.definitions, "", names, config)
    if config.module_level:
        units = chain([_to_unit(MODULE_UNIT_NAME, 1, scan, names, config)], units)
    layout = to_layout(source)
    return tuple(_place_branches(unit, layout) for unit in units)


def _place_branches(unit: Unit, layout: Layout) -> Unit:
    """Place a unit's branches on their opening lines, with the comments there, in order.

    The walk places an `else` branch at its first statement, since only the tokens show
    the line of the `else:` itself, and the comments.

    Args:
        unit: The unit as the walk built it.
        layout: The layout of the module's lines.

    Returns:
        The unit, with its branches at their opening lines, in order.
    """
    branches = []
    for branch in unit.branches:
        line = branch.line
        if branch.kind in _ELSE_KINDS:
            line = layout.find_else_line(branch.body_line)
        ignored = _find_ignored(layout.comments.get(line, ""))
        branches.append(replace(branch, line=line, ignored=ignored))
    return replace(unit, branches=tuple(sorted(branches, key=lambda branch: branch.line)))


def _find_ignored(comment: str) -> frozenset[FindingKind]:
    """Return the kinds of finding that a line's `# noqa` comment accepts.

    Codes birling does not have are skipped, as linters skip them, so a mistyped code leaves
    its finding in the report. A `# noqa` without codes accepts nothing: on a line that opens
    a branch, it is usually meant for a linter.

    Args:
        comment: The line's comment; empty when it has none.

    Returns:
        The kinds of finding whose codes the comment lists.
    """
    match = _NOQA_COMMENT.search(comment)
    if not match:
        return frozenset()
    known = set(FindingKind)
    codes = re.split(r"[\s,]+", match["codes"])
    return frozenset(FindingKind(code) for code in codes if code in known)


_Definition = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


class _Names(NamedTuple):
    """What the names in a unit refer to, where it matters to the measurement."""

    loggers: LoggerScope
    """The names that refer to loggers."""

    raising: frozenset[str]
    """The names, plain or dotted, that call a function that always raises."""

    functions: frozenset[str]
    """The functions that always raise, as configured."""

    def with_loggers(self, loggers: Iterable[str]) -> Self:
        """Return a copy that also takes `loggers` for loggers.

        Args:
            loggers: Names and dotted names that refer to loggers.

        Returns:
            The copy.
        """
        return self._replace(loggers=self.loggers.with_loggers(loggers))

    def with_bindings(self, bindings: Mapping[str, frozenset[str] | None]) -> Self:
        """Return a copy for a scope that binds names of its own.

        A name the scope binds hides the one outside it. A name it imports reaches a
        function that always raises when every import of it binds it to that function, or
        to the module the function is in: `from sys import exit` gives `exit`, and
        `import sys` gives `sys.exit`.

        Args:
            bindings: The names the scope binds, each with what imports bind it to.

        Returns:
            The copy.
        """
        kept = {name for name in self.raising if name.partition(".")[0] not in bindings}
        reached = {
            f"{bound}{suffix}"
            for bound, targets in bindings.items()
            if targets
            for suffix in _find_reached_suffixes(targets, self.functions)
        }
        return self._replace(raising=frozenset(kept | reached))


def _find_reached_suffixes(
    targets: frozenset[str], functions: frozenset[str]
) -> frozenset[str]:
    """Return what a name bound to every one of `targets` needs after it to call a raising one.

    An empty suffix means the name calls one itself, as `exit` does after `from sys import
    exit`; `.exit` follows `sys` after `import sys`. A plain name among `functions` is a
    built-in, reached through `builtins` as well.

    Args:
        targets: The dotted names that imports bind the name to.
        functions: The functions that always raise, as configured.

    Returns:
        The suffixes, the same for every target.
    """
    qualified = {name if "." in name else f"builtins.{name}" for name in functions}
    suffixes = (
        frozenset(
            name.removeprefix(target)
            for name in qualified
            if name == target or name.startswith(f"{target}.")
        )
        for target in targets
    )
    return frozenset.intersection(*suffixes)


class _Found(NamedTuple):
    """A branch as the walk finds it, before its log calls are recognised."""

    kind: BranchKind
    line: int
    condition: str
    exceptions: tuple[str, ...]
    body: list[ast.stmt]


@dataclass
class _Scan:
    """What a single walk finds in a unit's own code, before any call is recognised."""

    assignments: list[ast.Assign | ast.AnnAssign] = field(default_factory=list)
    branches: list[_Found] = field(default_factory=list)
    calls: list[tuple[ast.Call, tuple[int, ...]]] = field(default_factory=list)
    """Each call with the indices of the branches it is in."""
    definitions: list[_Definition] = field(default_factory=list)
    """The functions and classes defined in the code, which are not walked into."""


def _scan(statements: list[ast.stmt], config: Config) -> _Scan:
    """Walk a unit's own code once, gathering what the unit is built from.

    Args:
        statements: The unit's body.
        config: Whether lambdas are walked into.

    Returns:
        The assignments, branches, calls and definitions found.
    """
    scan = _Scan()
    # The index of the branch each statement directly in a branch's body belongs to.
    branch_of: dict[int, int] = {}
    stack: list[tuple[ast.AST, tuple[int, ...]]] = [(node, ()) for node in reversed(statements)]
    while stack:
        node, enclosing = stack.pop()
        if (index := branch_of.get(id(node))) is not None:
            enclosing = (*enclosing, index)
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                scan.definitions.append(node)
                continue
            case ast.Lambda(body=body):
                # A lambda's body runs when the lambda is called: it counts if configured.
                if config.lambdas:
                    stack.append((body, enclosing))
                continue
            case ast.Call():
                scan.calls.append((node, enclosing))
            case ast.Assign() | ast.AnnAssign():
                scan.assignments.append(node)
        for found in _to_branches(node):
            branch_of.update((id(statement), len(scan.branches)) for statement in found.body)
            scan.branches.append(found)
        children = reversed(list(ast.iter_child_nodes(node)))
        stack.extend((child, enclosing) for child in children)
    return scan


def _collect(
    definitions: Iterable[_Definition],
    prefix: str,
    names: _Names,
    config: Config,
) -> Iterator[Unit]:
    """Yield the units of functions and classes, and of those nested in them.

    Args:
        definitions: The functions and classes.
        prefix: The qualified name of the code they are defined in, with a trailing dot.
        names: What the names refer to where they are defined.
        config: What counts as a log call.

    Yields:
        The units, each one before those nested in it.
    """
    for definition in definitions:
        if isinstance(definition, ast.ClassDef):
            yield from _collect_class(definition, prefix, names, config)
        else:
            scan = _scan(definition.body, config)
            yield from _collect_function(definition, scan, prefix, names, config)


def _collect_class(
    definition: ast.ClassDef,
    prefix: str,
    names: _Names,
    config: Config,
) -> Iterator[Unit]:
    """Yield the units of a class's methods and nested classes.

    Every method is scanned before any unit is built, since a logger set on `self` in one
    serves them all.

    Args:
        definition: The class.
        prefix: The qualified name of the code it is defined in, with a trailing dot.
        names: What the names refer to where it is defined.
        config: What counts as a log call.

    Yields:
        The units, each one before those nested in it.
    """
    members = _scan(definition.body, config).definitions
    scans = {
        id(member): _scan(member.body, config)
        for member in members
        if not isinstance(member, ast.ClassDef)
    }
    attributes = {
        logger
        for scan in scans.values()
        for logger in find_loggers(scan.assignments, config)
        if logger.startswith("self.")
    }
    inner = names.with_loggers(attributes)
    inner_prefix = f"{prefix}{definition.name}."
    for member in members:
        if isinstance(member, ast.ClassDef):
            yield from _collect_class(member, inner_prefix, inner, config)
        else:
            yield from _collect_function(member, scans[id(member)], inner_prefix, inner, config)


def _collect_function(
    definition: ast.FunctionDef | ast.AsyncFunctionDef,
    scan: _Scan,
    prefix: str,
    names: _Names,
    config: Config,
) -> Iterator[Unit]:
    """Yield the unit of a function, then the units nested in it.

    Args:
        definition: The function.
        scan: The function's own code, already scanned.
        prefix: The qualified name of the code it is defined in, with a trailing dot.
        names: What the names refer to where it is defined.
        config: What counts as a log call.

    Yields:
        The units, each one before those nested in it.
    """
    name = f"{prefix}{definition.name}"
    bindings = find_bindings(walk_scope([definition.args, *definition.body]))
    inner = names.with_loggers(find_loggers(scan.assignments, config)).with_bindings(bindings)
    yield _to_unit(name, definition.lineno, scan, inner, config)
    yield from _collect(scan.definitions, f"{name}.", inner, config)


def _to_unit(
    name: str,
    line: int,
    scan: _Scan,
    names: _Names,
    config: Config,
) -> Unit:
    """Build a unit from its scanned code, recognising its log calls.

    Args:
        name: The unit's qualified name.
        line: The unit's first line.
        scan: The unit's own code, scanned.
        names: What the names in the unit refer to.
        config: What counts as a log call.

    Returns:
        The unit, with its branches in the order the walk found them.
    """
    calls = [
        (log_call, within)
        for call, within in scan.calls
        if (log_call := recognise(call, names.loggers, config))
    ]
    branches = (
        Branch(
            kind=found.kind,
            line=found.line,
            body_line=found.body[0].lineno,
            condition=found.condition,
            exceptions=found.exceptions,
            always_raises=_always_raises(found.body, names.raising),
            log_calls=tuple(log_call for log_call, within in calls if index in within),
        )
        for index, found in enumerate(scan.branches)
    )
    return Unit(
        name=name,
        line=line,
        branches=tuple(branches),
        log_calls=tuple(log_call for log_call, _ in calls),
    )


def _to_branches(node: ast.AST) -> Iterator[_Found]:
    """Yield the branches a node opens, without looking into its children.

    An `else` branch is placed at its first statement, since the syntax tree does not
    record the line of the `else:`.

    Args:
        node: Any node.

    Yields:
        Each branch the node opens.
    """
    match node:
        case ast.If(test=test, body=body, orelse=orelse):
            yield _Found(BranchKind.IF, node.lineno, ast.unparse(test), (), body)
            if orelse and not _is_elif(node):
                yield _Found(BranchKind.ELSE, orelse[0].lineno, "", (), orelse)
        case (
            ast.Try(handlers=handlers, orelse=orelse)
            | ast.TryStar(handlers=handlers, orelse=orelse)
        ):
            for handler in handlers:
                caught = ast.unparse(handler.type) if handler.type else ""
                exceptions = _to_exceptions(handler.type)
                yield _Found(
                    BranchKind.EXCEPT, handler.lineno, caught, exceptions, handler.body
                )
            if orelse:
                yield _Found(BranchKind.TRY_ELSE, orelse[0].lineno, "", (), orelse)
        case (
            ast.For(orelse=orelse) | ast.AsyncFor(orelse=orelse) | ast.While(orelse=orelse)
        ) if orelse:
            yield _Found(BranchKind.LOOP_ELSE, orelse[0].lineno, "", (), orelse)
        case ast.Match(cases=cases):
            for case in cases:
                pattern = ast.unparse(case.pattern)
                guard = f" if {ast.unparse(case.guard)}" if case.guard else ""
                condition = f"{pattern}{guard}"
                yield _Found(BranchKind.CASE, case.pattern.lineno, condition, (), case.body)


def _to_exceptions(caught: ast.expr | None) -> tuple[str, ...]:
    """Return the exception types an `except` names, as written.

    Args:
        caught: What the `except` names: a type, a tuple of them, or nothing.

    Returns:
        The types; none for a bare `except`.
    """
    match caught:
        case None:
            return ()
        case ast.Tuple(elts=elements):
            return tuple(ast.unparse(element) for element in elements)
    return (ast.unparse(caught),)


def _is_elif(node: ast.If) -> bool:
    """Tell whether the `else` of an `if` is an `elif`.

    An `elif` is an `if` alone in the `else`, starting at the same column as the outer `if`;
    an `if` nested in an `else` is indented further.

    Args:
        node: An `if` with an `else`.

    Returns:
        Whether the `else` is an `elif`.
    """
    [first, *rest] = node.orelse
    return not rest and isinstance(first, ast.If) and first.col_offset == node.col_offset


def _always_raises(statements: list[ast.stmt], raising: frozenset[str]) -> bool:
    """Tell whether every path through a block of statements ends by raising.

    The statements are followed in order: the block raises at the first statement that
    always raises, unless an earlier one offers a way out.

    Args:
        statements: The block.
        raising: The names, as the module writes them, of the functions that always raise.

    Returns:
        Whether every path through the block raises.
    """
    for statement in statements:
        if _raises(statement, raising):
            return True
        if _escapes(statement):
            return False
    return False


def _raises(statement: ast.stmt, raising: frozenset[str]) -> bool:
    """Tell whether every path through a statement ends by raising.

    A call to a function that always raises raises, as a statement of its own or returned,
    awaited or not. A compound statement raises when all of its paths do; a `match` needs a
    last case that catches everything. A loop may not run at all, so it never counts as
    raising.

    Args:
        statement: The statement.
        raising: The names, as the module writes them, of the functions that always raise.

    Returns:
        Whether every path through the statement raises.
    """
    if isinstance(statement, ast.Raise) or _calls_raising(statement, raising):
        return True
    match statement:
        case ast.If(body=body, orelse=orelse):
            return _always_raises(body, raising) and _always_raises(orelse, raising)
        case ast.With(body=body) | ast.AsyncWith(body=body):
            return _always_raises(body, raising)
        case (
            ast.Try(body=body, handlers=handlers, orelse=orelse, finalbody=finalbody)
            | ast.TryStar(body=body, handlers=handlers, orelse=orelse, finalbody=finalbody)
        ):
            handled = all(_always_raises(handler.body, raising) for handler in handlers)
            completed = _always_raises(body, raising) or _always_raises(orelse, raising)
            return _always_raises(finalbody, raising) or (handled and completed)
        case ast.Match(cases=cases):
            last = cases[-1].pattern
            catches_all = isinstance(last, ast.MatchAs) and last.pattern is None
            return (
                catches_all
                and cases[-1].guard is None
                and all(_always_raises(case.body, raising) for case in cases)
            )
    return False


def _calls_raising(statement: ast.stmt, raising: frozenset[str]) -> bool:
    """Tell whether a statement is a call to a function that always raises, or returns one.

    Args:
        statement: The statement.
        raising: The names, as the module writes them, of the functions that always raise.

    Returns:
        Whether the statement is such a call, awaited or not.
    """
    match statement:
        case (
            ast.Expr(value=ast.Call(func=func) | ast.Await(value=ast.Call(func=func)))
            | ast.Return(value=ast.Call(func=func) | ast.Await(value=ast.Call(func=func)))
        ):
            return to_dotted_name(func) in raising
    return False


def _escapes(statement: ast.stmt) -> bool:
    """Tell whether a statement holds a way out of its block other than raising.

    A way out is a `return`, or a `break` or `continue` that leaves the loop around the
    block rather than one within the statement. Nested functions, classes and lambdas are
    not looked into.

    Args:
        statement: The statement.

    Returns:
        Whether the statement holds a way out.
    """
    stack: list[tuple[ast.AST, bool]] = [(statement, False)]
    while stack:
        node, in_loop = stack.pop()
        match node:
            case ast.Return():
                return True
            case ast.Break() | ast.Continue() if not in_loop:
                return True
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() | ast.Lambda():
                continue
            case (
                ast.For(body=body, orelse=orelse)
                | ast.AsyncFor(body=body, orelse=orelse)
                | ast.While(body=body, orelse=orelse)
            ):
                stack.extend((child, True) for child in body)
                stack.extend((child, in_loop) for child in orelse)
                continue
        stack.extend((child, in_loop) for child in ast.iter_child_nodes(node))
    return False
