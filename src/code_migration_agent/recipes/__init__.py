"""Recipe registry. Order is deterministic and idempotent."""

from __future__ import annotations

from collections.abc import Sequence

from .base import Recipe, RecipeParseError
from .builtins import RECIPE as _builtin_aliases
from .dicts import RECIPE as _dict_methods
from .imports import RECIPE as _moved_imports

RECIPES: dict[str, Recipe] = {
    recipe.recipe_id: recipe
    for recipe in (_moved_imports, _builtin_aliases, _dict_methods)
}
RECIPE_IDS: tuple[str, ...] = tuple(RECIPES)


def apply_recipes(
    source: str, recipe_ids: Sequence[str] = RECIPE_IDS
) -> tuple[str, dict[str, int]]:
    """Apply recipes in order; each edit count is per rule."""
    current = source
    counts: dict[str, int] = {}
    for recipe_id in recipe_ids:
        recipe = RECIPES.get(recipe_id)
        if recipe is None:
            raise KeyError(f"unknown recipe: {recipe_id}")
        updated, count = recipe.apply(current)
        if count:
            current = updated
            counts[recipe_id] = count
    return current, counts


__all__ = [
    "RECIPES",
    "RECIPE_IDS",
    "Recipe",
    "RecipeParseError",
    "apply_recipes",
]
