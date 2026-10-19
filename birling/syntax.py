"""Helpers for reading Python's syntax tree and what it leaves out."""

import ast
import io
import tokenize
import warnings
from bisect import bisect_right
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from itertools import pairwise

NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
"""Nodes that open a scope of their own, whose code does not run where it is written."""


def walk_scope(nodes: Iterable[ast.AST]) -> Iterator[ast.AST]:
    """Yield the nodes and their descendants, depth first, without entering nested scopes.

    A nested function, class or lambda is yielded itself, but nothing inside it is.

    Args:
        nodes: The nodes to walk.

    Yields:
        The nodes, each one before its descendants.
    """
    stack = list(reversed(list(nodes)))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, NESTED_SCOPES):
            stack.extend(reversed(list(ast.iter_child_nodes(node))))


def to_dotted_name(node: ast.AST) -> str | None:
    """Return the dotted name an expression spells, such as `self.logger`.

    Args:
        node: The expression.

    Returns:
        The dotted name, or `None` when the expression is not a name or attributes of one.
    """
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=value, attr=attr):
            prefix = to_dotted_name(value)
            return None if prefix is None else f"{prefix}.{attr}"
    return None


_Definition = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def find_bindings(nodes: Iterable[ast.AST]) -> dict[str, frozenset[str] | None]:
    """Return the names that the nodes of one scope bind, with what imports bind them to.

    Every way of binding a name counts: parameters, assignment targets, `def` and `class`,
    imports, `except ... as`, the captures of a `match` pattern, and names bound under
    `global` or `nonlocal` in nested functions. The variables of a comprehension's `for`
    belong to the comprehension, so they are left out, and so are the names of a `*` import,
    which cannot be told from the source.

    Args:
        nodes: The scope's own nodes, in the order `walk_scope()` yields them; a function's
            parameters are included by walking its `args` along with its body.

    Returns:
        The bound names, each with every dotted name an import binds it to, such as
        `sys.exit` for `from sys import exit`; `None` when anything else binds it, or an
        import whose target cannot be told.
    """
    scope_nodes = list(nodes)
    found: dict[str, set[str] | None] = {}
    for name, target in _find_each_binding(scope_nodes):
        targets = found.get(name, set())
        found[name] = None if targets is None or target is None else targets | {target}
    for name in _find_rebound_in_scope(scope_nodes):
        found[name] = None
    return {
        name: None if targets is None else frozenset(targets) for name, targets in found.items()
    }


def _find_rebound_in_scope(nodes: list[ast.AST]) -> set[str]:
    """Return the names that nested scopes rebind in this scope through `global` or `nonlocal`.

    Args:
        nodes: The scope's own nodes.

    Returns:
        The names rebound in this scope.
    """
    is_function = any(isinstance(node, ast.arguments) for node in nodes)
    rebound: set[str] = set()
    for node in nodes:
        if isinstance(node, _Definition):
            global_names, nonlocal_names = _find_rebound(node)
            rebound |= nonlocal_names if is_function else global_names
    return rebound


def _find_rebound(scope: _Definition) -> tuple[set[str], set[str]]:
    """Return the names that a nested scope and its descendants rebind outside it.

    Args:
        scope: The nested function or class.

    Returns:
        The names rebound under `global` and under `nonlocal`.
    """
    body: list[ast.AST] = (
        [*scope.body] if isinstance(scope, ast.ClassDef) else [scope.args, *scope.body]
    )
    nodes = list(walk_scope(body))
    declared_global = {
        name for node in nodes if isinstance(node, ast.Global) for name in node.names
    }
    declared_nonlocal = {
        name for node in nodes if isinstance(node, ast.Nonlocal) for name in node.names
    }
    direct_bound = {name for name, _ in _find_each_binding(nodes)}
    global_names = direct_bound & declared_global
    nonlocal_names = direct_bound & declared_nonlocal
    child_nonlocals: set[str] = set()
    for node in nodes:
        if isinstance(node, _Definition):
            child_global, child_nonlocal = _find_rebound(node)
            global_names |= child_global
            child_nonlocals |= child_nonlocal
    if isinstance(scope, ast.ClassDef):
        nonlocal_names |= child_nonlocals
    else:
        local_bound = direct_bound - declared_global - declared_nonlocal
        nonlocal_names |= child_nonlocals - local_bound
    return global_names, nonlocal_names


def _find_each_binding(nodes: Iterable[ast.AST]) -> Iterator[tuple[str, str | None]]:
    """Yield each direct binding of a name among the nodes, in their order.

    A comprehension comes before the variables of its `for`, which are skipped.

    Args:
        nodes: The nodes, each before its descendants.

    Yields:
        The bound name, with the dotted name an import binds it to, or `None`.
    """
    in_comprehension: set[int] = set()
    for node in nodes:
        match node:
            case ast.comprehension(target=target):
                in_comprehension.update(id(name) for name in ast.walk(target))
            case ast.Import() | ast.ImportFrom():
                yield from _find_import_bindings(node)
            case ast.Name(id=name, ctx=ast.Store() | ast.Del()) if (
                id(node) not in in_comprehension
            ):
                yield name, None
            case (
                ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
                | ast.arg(arg=name)
            ):
                yield name, None
            case (
                ast.ExceptHandler(name=str() as name)
                | ast.MatchAs(name=str() as name)
                | ast.MatchStar(name=str() as name)
                | ast.MatchMapping(rest=str() as name)
            ):
                yield name, None


def _find_import_bindings(
    node: ast.Import | ast.ImportFrom,
) -> Iterator[tuple[str, str | None]]:
    """Yield the names an import binds, with what it binds them to.

    A relative import binds names to modules that cannot be told from the source alone.

    Args:
        node: The import.

    Yields:
        The bound name, with the dotted name it is bound to, or `None` when that is unknown.
    """
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.asname:
                yield alias.asname, alias.name
            else:
                first = alias.name.partition(".")[0]
                yield first, first
        return
    prefix = f"{node.module}." if node.module is not None and node.level == 0 else None
    for alias in node.names:
        if alias.name != "*":
            yield alias.asname or alias.name, None if prefix is None else prefix + alias.name


def parse(source: str) -> ast.Module:
    """Parse a module's source without showing warnings.

    A warning about the parsed code, such as an invalid escape, is for that code's own
    tools, whatever its category: the category of some warnings differs between Python
    versions.

    Args:
        source: The module's source.

    Returns:
        The module's syntax tree.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ast.parse(source)


@dataclass(frozen=True)
class Layout:
    """What a module's syntax tree leaves out about its lines."""

    else_lines: tuple[int, ...]
    """The lines of the `else:` that open blocks, in order."""

    comments: Mapping[int, str]
    """The comments, by line."""

    def find_else_line(self, line: int) -> int:
        """Return the line of the `else:` that opens a block.

        Args:
            line: The line of the block's first statement.

        Returns:
            The line of the last `else:` at or before it.
        """
        return self.else_lines[bisect_right(self.else_lines, line) - 1]


def to_layout(source: str) -> Layout:
    """Read from a module's tokens what its syntax tree leaves out.

    An `else` opens a block when a colon follows it; the `else` of a conditional expression
    does not.

    Args:
        source: The module's source.

    Returns:
        The layout of the module's lines.
    """
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    else_lines = tuple(
        token.start[0]
        for token, following in pairwise(tokens)
        if token.type == tokenize.NAME and token.string == "else" and following.string == ":"
    )
    comments = {
        token.start[0]: token.string for token in tokens if token.type == tokenize.COMMENT
    }
    return Layout(else_lines, comments)
