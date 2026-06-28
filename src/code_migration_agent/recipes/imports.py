"""Rewrite imports moved or renamed between Python 2 and Python 3."""

from __future__ import annotations

import libcst as cst

from .base import Recipe, apply_transformer

MOVED_MODULES: dict[str, str] = {
    "ConfigParser": "configparser",
    "Queue": "queue",
    "cPickle": "pickle",
    "cStringIO": "io",
    "StringIO": "io",
    "urllib2": "urllib.request",
    "urlparse": "urllib.parse",
    "httplib": "http.client",
    "HTMLParser": "html.parser",
    "SocketServer": "socketserver",
    "copy_reg": "copyreg",
    "thread": "_thread",
    "repr": "reprlib",
}

DEFAULT_RECIPE_MODULES: dict[str, str] = {
    module: target
    for module, target in MOVED_MODULES.items()
    if module not in {"urllib2", "urlparse"}
}

ITERTOOLS_RENAMES: dict[str, str] = {
    "izip": "zip",
    "imap": "map",
    "ifilter": "filter",
}


def _dotted(node: cst.CSTNode | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        base = _dotted(node.value)
        return None if base is None else f"{base}.{node.attr.value}"
    return None


def _name_expr(dotted: str) -> cst.BaseExpression:
    return cst.parse_expression(dotted)


def _local_name(alias: cst.ImportAlias) -> str | None:
    if alias.asname is not None:
        name = alias.asname.name
        return name.value if isinstance(name, cst.Name) else None
    if isinstance(alias.name, cst.Name):
        return alias.name.value
    if isinstance(alias.name, cst.Attribute):
        return _dotted(alias.name)
    return None  # type: ignore[unreachable]


def _imported_name(alias: cst.ImportAlias) -> str | None:
    return alias.name.value if isinstance(alias.name, cst.Name) else None


class _Collector(cst.CSTVisitor):
    def __init__(self, modules: dict[str, str]) -> None:
        self.modules = modules
        self.unaliased_roots: set[str] = set()
        self.itertools_locals: dict[str, str] = {}

    def visit_Import(self, node: cst.Import) -> None:
        for alias in node.names:
            module = _dotted(alias.name)
            if module not in self.modules:
                continue
            if alias.asname is not None:
                continue
            self.unaliased_roots.add(module)

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        module = _dotted(node.module)
        if module != "itertools" or isinstance(node.names, cst.ImportStar):
            return
        for alias in node.names:
            imported = _imported_name(alias)
            local = _local_name(alias)
            if imported is None or local is None or imported not in ITERTOOLS_RENAMES:
                continue
            self.itertools_locals[local] = ITERTOOLS_RENAMES[imported]


class _ImportTransformer(cst.CSTTransformer):
    def __init__(self, collected: _Collector, modules: dict[str, str]) -> None:
        self.modules = modules
        self.unaliased_roots = collected.unaliased_roots
        self.itertools_locals = collected.itertools_locals
        self.count = 0
        self._in_import = 0

    def visit_Import(self, node: cst.Import) -> None:
        self._in_import += 1

    def leave_Import(
        self, original_node: cst.Import, updated_node: cst.Import
    ) -> cst.Import:
        self._in_import -= 1
        aliases: list[cst.ImportAlias] = []
        changed = False
        for alias in updated_node.names:
            module = _dotted(alias.name)
            if module is not None and module in self.modules:
                alias = alias.with_changes(name=_name_expr(self.modules[module]))
                changed = True
                self.count += 1
            aliases.append(alias)
        return updated_node.with_changes(names=tuple(aliases)) if changed else updated_node

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        self._in_import += 1

    def leave_ImportFrom(
        self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom
    ) -> cst.ImportFrom | cst.RemovalSentinel:
        self._in_import -= 1
        module = _dotted(updated_node.module)
        new_module = self.modules.get(module) if module is not None else None
        if new_module is not None:
            updated_node = updated_node.with_changes(module=_name_expr(new_module))
            self.count += 1
        if module == "itertools" and not isinstance(updated_node.names, cst.ImportStar):
            kept: list[cst.ImportAlias] = []
            changed = False
            for alias in updated_node.names:
                imported = _imported_name(alias)
                if imported is not None and imported in ITERTOOLS_RENAMES:
                    changed = True
                    self.count += 1
                    continue
                kept.append(alias)
            if changed:
                if not kept:
                    return cst.RemoveFromParent()
                updated_node = updated_node.with_changes(names=tuple(kept))
        return updated_node

    def leave_Attribute(
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.Attribute:
        if self._in_import:
            return updated_node
        if isinstance(updated_node.value, cst.Name):
            root = updated_node.value.value
            if root in self.unaliased_roots and root in self.modules:
                self.count += 1
                return updated_node.with_changes(value=_name_expr(self.modules[root]))
        return updated_node

    def leave_Call(
        self, original_node: cst.Call, updated_node: cst.Call
    ) -> cst.Call:
        if isinstance(updated_node.func, cst.Name):
            target = self.itertools_locals.get(updated_node.func.value)
            if target is not None:
                self.count += 1
                return updated_node.with_changes(func=cst.Name(target))
        return updated_node


def apply_moved_modules(
    source: str, modules: dict[str, str]
) -> tuple[str, int]:
    try:
        collected = _Collector(modules)
        cst.parse_module(source).visit(collected)
    except cst.ParserSyntaxError:
        return source, 0
    transformer = _ImportTransformer(collected, modules)
    _, code = apply_transformer(source, transformer)
    if transformer.count == 0:
        return source, 0
    return code, transformer.count


def _apply(source: str) -> tuple[str, int]:
    return apply_moved_modules(source, DEFAULT_RECIPE_MODULES)


RECIPE = Recipe(
    recipe_id="moved_imports",
    description=(
        "Rewrite safe Python 2 stdlib module moves and itertools aliases; "
        "URL modules are reserved for the agent."
    ),
    apply=_apply,
)
