import ast
import keyword
import warnings
from textwrap import dedent

import pytest
from hypothesis import given, strategies as st

from birling.syntax import (
    NESTED_SCOPES,
    Layout,
    parse,
    to_dotted_name,
    to_layout,
    walk_scope,
)

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


def test_parse_returns_the_syntax_tree_without_showing_warnings():
    """A warning such as an invalid escape is for the parsed code's own tools."""
    source = 'pattern = "\\d+"\n'

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        module = parse(source)

    [assignment] = module.body
    assert assignment.value.value == "\\d+"


def test_to_layout_finds_the_comments_and_the_else_that_opens_a_block():
    """An `else` followed by a colon opens a block; that of a conditional expression does not."""
    source = dedent("""
        if ready:
            value = start() if ready else stop()
        else:  # noqa: BRL001
            value = None
        for item in items:
            pass  # nothing to do
        else: done()
    """)

    layout = to_layout(source)

    assert layout == Layout(
        else_lines=(4, 8), comments={4: "# noqa: BRL001", 7: "# nothing to do"}
    )


def test_a_layout_finds_the_else_that_opens_the_block_starting_on_a_line():
    layout = Layout(else_lines=(4, 8), comments={})

    else_line = layout.find_else_line(6)

    assert else_line == 4
