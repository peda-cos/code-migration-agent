"""Rewrite Python 2 builtin aliases in call and isinstance positions."""

from __future__ import annotations

import libcst as cst

from .base import Recipe, apply_transformer

BUILTIN_RENAMES: dict[str, str] = {
    "unicode": "str",
    "basestring": "str",
    "long": "int",
    "xrange": "range",
    "raw_input": "input",
    "unichr": "chr",
}


def _replace_basestring(node: cst.BaseExpression) -> tuple[cst.BaseExpression, int]:
    if isinstance(node, cst.Name) and node.value == "basestring":
        return cst.Name("str"), 1
    if isinstance(node, cst.Tuple):
        count = 0
        elements: list[cst.Element] = []
        for element in node.elements:
            if not isinstance(element, cst.Element):
                return node, 0
            value, changed = _replace_basestring(element.value)
            count += changed
            elements.append(element.with_changes(value=value))
        if count:
            return node.with_changes(elements=tuple(elements)), count
    return node, 0


class _BuiltinTransformer(cst.CSTTransformer):
    def __init__(self) -> None:
        self.count = 0

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        if isinstance(updated_node.func, cst.Name):
            renamed = BUILTIN_RENAMES.get(updated_node.func.value)
            if renamed is not None:
                self.count += 1
                updated_node = updated_node.with_changes(func=cst.Name(renamed))
        if isinstance(updated_node.func, cst.Name) and updated_node.func.value == "isinstance":
            if len(updated_node.args) >= 2:
                old_arg = updated_node.args[1]
                new_value, changed = _replace_basestring(old_arg.value)
                if changed:
                    self.count += changed
                    args = list(updated_node.args)
                    args[1] = old_arg.with_changes(value=new_value)
                    updated_node = updated_node.with_changes(args=tuple(args))
        return updated_node


def _apply(source: str) -> tuple[str, int]:
    transformer = _BuiltinTransformer()
    try:
        _, code = apply_transformer(source, transformer)
    except cst.ParserSyntaxError:
        return source, 0
    if transformer.count == 0:
        return source, 0
    return code, transformer.count


RECIPE = Recipe(
    recipe_id="builtin_aliases",
    description="Replace unicode/xrange/raw_input/basestring and friends.",
    apply=_apply,
)
