"""Helpers for reading Python's syntax tree."""

import ast
from collections.abc import Iterable, Iterator

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
