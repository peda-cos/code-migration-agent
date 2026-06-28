"""Rewrite Python 2 dict methods to Python 3 equivalents."""

from __future__ import annotations

import libcst as cst

from .base import Recipe, apply_transformer, code_for

DICT_RENAMES = {
    "iteritems": "items",
    "iterkeys": "keys",
    "itervalues": "values",
}


class _DictTransformer(cst.CSTTransformer):
    def __init__(self) -> None:
        self.count = 0

    def leave_Call(
        self, original_node: cst.Call, updated_node: cst.Call
    ) -> cst.BaseExpression:
        if not isinstance(updated_node.func, cst.Attribute):
            return updated_node
        attr = updated_node.func.attr.value
        if attr in DICT_RENAMES and not updated_node.args:
            self.count += 1
            return updated_node.with_changes(
                func=updated_node.func.with_changes(attr=cst.Name(DICT_RENAMES[attr]))
            )
        if attr == "has_key" and len(updated_node.args) == 1:
            argument = updated_node.args[0]
            if argument.star:
                return updated_node
            result = cst.parse_expression(
                f"({code_for(argument.value)}) in ({code_for(updated_node.func.value)})"
            )
            self.count += 1
            return result
        if attr == "next" and not updated_node.args:
            self.count += 1
            return cst.Call(
                func=cst.Name("next"),
                args=[cst.Arg(value=updated_node.func.value)],
            )
        return updated_node


def _apply(source: str) -> tuple[str, int]:
    transformer = _DictTransformer()
    try:
        _, code = apply_transformer(source, transformer)
    except cst.ParserSyntaxError:
        return source, 0
    if transformer.count == 0:
        return source, 0
    return code, transformer.count


RECIPE = Recipe(
    recipe_id="dict_methods",
    description="Rewrite has_key and iteritems/iterkeys/itervalues/next.",
    apply=_apply,
)
