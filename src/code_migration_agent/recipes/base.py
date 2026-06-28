"""Recipe primitives and shared libcst helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import libcst as cst


@dataclass(frozen=True)
class Recipe:
    recipe_id: str
    description: str
    apply: Callable[[str], tuple[str, int]]


def code_for(node: cst.CSTNode) -> str:
    """Serialize a single CST node without a module wrapper."""
    return cst.Module([]).code_for_node(node)


def parse_module(source: str) -> cst.Module:
    return cst.parse_module(source)


class RecipeParseError(RuntimeError):
    """Raised when a recipe receives source libcst cannot parse."""


def apply_transformer(
    source: str, transformer: cst.CSTTransformer
) -> tuple[cst.Module, str]:
    """Parse, visit, and return the updated module plus its code."""
    try:
        module = parse_module(source)
    except cst.ParserSyntaxError as exc:
        raise RecipeParseError(str(exc)) from exc
    updated = module.visit(transformer)
    return updated, updated.code
