import ast
import keyword
from textwrap import dedent

from hypothesis import given
from hypothesis import strategies as st
import pytest

from birling.syntax import NESTED_SCOPES, to_dotted_name, walk_scope

identifiers = st.from_regex(r"[A-Za-z_][A-Za-z0-9_]*", fullmatch=True).filter(
    lambda name: not keyword.iskeyword(name)
)


def test_walk_scope_yields_the_nodes_and_their_descendants_depth_first():
    source = dedent("""
        if ready:
            start(now)
        stop()
    """)
    statements = ast.parse(source).body

    nodes = list(walk_scope(statements))

    assert [node.id for node in nodes if isinstance(node, ast.Name)] == [
        "ready",
        "start",
        "now",
        "stop",
    ]


def test_walk_scope_yields_a_nested_scope_without_entering_it():
    source = dedent("""
        def inner():
            hidden()

        class Inner:
            hidden = 1

        callback = lambda: hidden()
    """)
    statements = ast.parse(source).body
    inner_function, inner_class, assignment = statements

    nodes = list(walk_scope(statements))

    scopes = [node for node in nodes if isinstance(node, NESTED_SCOPES)]
    assert scopes == [inner_function, inner_class, assignment.value]
    assert [node.id for node in nodes if isinstance(node, ast.Name)] == ["callback"]


@pytest.mark.parametrize(
    ("expression", "name"),
    [
        ("log", "log"),
        ("self.logger", "self.logger"),
        ("app.state.logger", "app.state.logger"),
    ],
)
def test_to_dotted_name_spells_out_a_name_or_attribute(expression, name):
    node = ast.parse(expression, mode="eval").body

    dotted_name = to_dotted_name(node)

    assert dotted_name == name


@given(st.lists(identifiers, min_size=1, max_size=4).map(".".join))
def test_to_dotted_name_spells_out_any_dotted_name(dotted):
    node = ast.parse(dotted, mode="eval").body

    dotted_name = to_dotted_name(node)

    assert dotted_name == dotted


@pytest.mark.parametrize(
    "expression", ["loggers['events']", "make_logger()", "make_logger().events", "1"]
)
def test_to_dotted_name_returns_none_for_any_other_expression(expression):
    node = ast.parse(expression, mode="eval").body

    dotted_name = to_dotted_name(node)

    assert dotted_name is None
