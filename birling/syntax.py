"""Helpers for reading Python's syntax tree and what it leaves out."""

import ast
from bisect import bisect_right
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
import io
from itertools import pairwise
import tokenize
import warnings

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
