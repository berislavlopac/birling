"""Finding the units of a module, with their branches and log calls."""

import ast
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from itertools import chain

from birling.config import BranchKind, Config
from birling.recognition import (
    LogCall,
    LoggerScope,
    find_loggers,
    find_module_scope,
    recognise,
)
from birling.syntax import Layout, parse, to_layout

MODULE_UNIT_NAME = "<module>"
"""The name of the unit that holds a module's own code, as Python names its code object."""

# The kinds of branch opened by an `else:`, whose line the syntax tree does not record.
_ELSE_KINDS = frozenset({BranchKind.ELSE, BranchKind.TRY_ELSE, BranchKind.LOOP_ELSE})


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

    always_raises: bool
    """Whether every path through the branch ends by raising."""

    log_calls: tuple[LogCall, ...]
    """The log calls in the branch, those in its nested statements included.

    Those in lambdas are included only when the configuration says so.
    """

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
    scope = find_module_scope(module, config)
    scan = _scan(module.body, config)
    units = _collect(scan.definitions, "", scope, config)
    if config.module_level:
        units = chain([_to_unit(MODULE_UNIT_NAME, 1, scan, scope, config)], units)
    layout = to_layout(source)
    return tuple(_place_branches(unit, layout) for unit in units)


def _place_branches(unit: Unit, layout: Layout) -> Unit:
    """Move a unit's `else` branches to their `else:` line, and order its branches by line.

    The walk places an `else` branch at its first statement, since only the tokens show
    the line of the `else:` itself.

    Args:
        unit: The unit as the walk built it.
        layout: The layout of the module's lines.

    Returns:
        The unit, with its branches at their opening lines, in order.
    """
    branches = (
        replace(branch, line=layout.find_else_line(branch.body_line))
        if branch.kind in _ELSE_KINDS
        else branch
        for branch in unit.branches
    )
    return replace(unit, branches=tuple(sorted(branches, key=lambda branch: branch.line)))


_Definition = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


@dataclass
class _Scan:
    """What a single walk finds in a unit's own code, before any call is recognised."""

    assignments: list[ast.Assign | ast.AnnAssign] = field(default_factory=list)
    branches: list[tuple[BranchKind, int, str, list[ast.stmt]]] = field(default_factory=list)
    """Each branch's kind, opening line, condition and body."""
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
        for kind, line, condition, body in _to_branches(node):
            branch_of.update((id(statement), len(scan.branches)) for statement in body)
            scan.branches.append((kind, line, condition, body))
        children = reversed(list(ast.iter_child_nodes(node)))
        stack.extend((child, enclosing) for child in children)
    return scan


def _collect(
    definitions: Iterable[_Definition], prefix: str, scope: LoggerScope, config: Config
) -> Iterator[Unit]:
    """Yield the units of functions and classes, and of those nested in them.

    Args:
        definitions: The functions and classes.
        prefix: The qualified name of the code they are defined in, with a trailing dot.
        scope: The loggers known where they are defined.
        config: What counts as a log call.

    Yields:
        The units, each one before those nested in it.
    """
    for definition in definitions:
        if isinstance(definition, ast.ClassDef):
            yield from _collect_class(definition, prefix, scope, config)
        else:
            scan = _scan(definition.body, config)
            yield from _collect_function(definition, scan, prefix, scope, config)


def _collect_class(
    definition: ast.ClassDef, prefix: str, scope: LoggerScope, config: Config
) -> Iterator[Unit]:
    """Yield the units of a class's methods and nested classes.

    Every method is scanned before any unit is built, since a logger set on `self` in one
    serves them all.

    Args:
        definition: The class.
        prefix: The qualified name of the code it is defined in, with a trailing dot.
        scope: The loggers known where it is defined.
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
    inner = scope.with_loggers(attributes)
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
    scope: LoggerScope,
    config: Config,
) -> Iterator[Unit]:
    """Yield the unit of a function, then the units nested in it.

    Args:
        definition: The function.
        scan: The function's own code, already scanned.
        prefix: The qualified name of the code it is defined in, with a trailing dot.
        scope: The loggers known where it is defined.
        config: What counts as a log call.

    Yields:
        The units, each one before those nested in it.
    """
    name = f"{prefix}{definition.name}"
    inner = scope.with_loggers(find_loggers(scan.assignments, config))
    yield _to_unit(name, definition.lineno, scan, inner, config)
    yield from _collect(scan.definitions, f"{name}.", inner, config)


def _to_unit(name: str, line: int, scan: _Scan, scope: LoggerScope, config: Config) -> Unit:
    """Build a unit from its scanned code, recognising its log calls.

    Args:
        name: The unit's qualified name.
        line: The unit's first line.
        scan: The unit's own code, scanned.
        scope: The loggers known in the unit.
        config: What counts as a log call.

    Returns:
        The unit, with its branches in the order the walk found them.
    """
    calls = [
        (log_call, within)
        for call, within in scan.calls
        if (log_call := recognise(call, scope, config))
    ]
    branches = (
        Branch(
            kind=kind,
            line=opening,
            body_line=body[0].lineno,
            condition=condition,
            always_raises=_always_raises(body),
            log_calls=tuple(log_call for log_call, within in calls if index in within),
        )
        for index, (kind, opening, condition, body) in enumerate(scan.branches)
    )
    return Unit(
        name=name,
        line=line,
        branches=tuple(branches),
        log_calls=tuple(log_call for log_call, _ in calls),
    )


def _to_branches(node: ast.AST) -> Iterator[tuple[BranchKind, int, str, list[ast.stmt]]]:
    """Yield the branches a node opens, without looking into its children.

    An `else` branch is placed at its first statement, since the syntax tree does not
    record the line of the `else:`.

    Args:
        node: Any node.

    Yields:
        Each branch's kind, opening line, condition and body.
    """
    match node:
        case ast.If(test=test, body=body, orelse=orelse):
            yield BranchKind.IF, node.lineno, ast.unparse(test), body
            if orelse and not _is_elif(node):
                yield BranchKind.ELSE, orelse[0].lineno, "", orelse
        case (
            ast.Try(handlers=handlers, orelse=orelse)
            | ast.TryStar(handlers=handlers, orelse=orelse)
        ):
            for handler in handlers:
                caught = ast.unparse(handler.type) if handler.type else ""
                yield BranchKind.EXCEPT, handler.lineno, caught, handler.body
            if orelse:
                yield BranchKind.TRY_ELSE, orelse[0].lineno, "", orelse
        case (
            ast.For(orelse=orelse) | ast.AsyncFor(orelse=orelse) | ast.While(orelse=orelse)
        ) if orelse:
            yield BranchKind.LOOP_ELSE, orelse[0].lineno, "", orelse
        case ast.Match(cases=cases):
            for case in cases:
                pattern = ast.unparse(case.pattern)
                guard = f" if {ast.unparse(case.guard)}" if case.guard else ""
                yield BranchKind.CASE, case.pattern.lineno, f"{pattern}{guard}", case.body


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


def _always_raises(statements: list[ast.stmt]) -> bool:
    """Tell whether every path through a block of statements ends by raising.

    The statements are followed in order: the block raises at the first statement that
    always raises, unless an earlier one offers a way out.

    Args:
        statements: The block.

    Returns:
        Whether every path through the block raises.
    """
    for statement in statements:
        if _escapes(statement):
            return False
        if _raises(statement):
            return True
    return False


def _raises(statement: ast.stmt) -> bool:
    """Tell whether every path through a statement ends by raising.

    A compound statement raises when all of its paths do; a `match` needs a last case that
    catches everything. A loop may not run at all, so it never counts as raising.

    Args:
        statement: The statement.

    Returns:
        Whether every path through the statement raises.
    """
    match statement:
        case ast.Raise():
            return True
        case ast.If(body=body, orelse=orelse):
            return _always_raises(body) and _always_raises(orelse)
        case ast.With(body=body) | ast.AsyncWith(body=body):
            return _always_raises(body)
        case (
            ast.Try(body=body, handlers=handlers, orelse=orelse, finalbody=finalbody)
            | ast.TryStar(body=body, handlers=handlers, orelse=orelse, finalbody=finalbody)
        ):
            handled = all(_always_raises(handler.body) for handler in handlers)
            completed = _always_raises(body) or _always_raises(orelse)
            return _always_raises(finalbody) or (handled and completed)
        case ast.Match(cases=cases):
            last = cases[-1].pattern
            catches_all = isinstance(last, ast.MatchAs) and last.pattern is None
            return (
                catches_all
                and cases[-1].guard is None
                and all(_always_raises(case.body) for case in cases)
            )
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
