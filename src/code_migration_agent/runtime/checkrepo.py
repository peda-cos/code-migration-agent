"""Build check executed inside the target repository workspace."""

from __future__ import annotations

import importlib
import pkgutil
import sys
import traceback
from pathlib import Path


def _compile_tree(root: Path, label: str) -> str | None:
    if not root.exists():
        return f"{label} directory not found: {root}"
    for path in sorted(root.rglob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
        except (OSError, UnicodeDecodeError) as exc:
            return f"{label} read error in {path}: {exc}"
        except SyntaxError as exc:
            line = exc.lineno if exc.lineno is not None else 0
            return f"{label} SyntaxError in {path}:{line}: {exc.msg}"
    return None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        print("usage: checkrepo <root> <package> <test_dir>", file=sys.stderr)
        return 2
    root = Path(args[0]).resolve()
    package = args[1]
    test_dir = root / args[2]
    package_dir = root / package.replace(".", "/")
    error = _compile_tree(package_dir, "package")
    if error is None:
        error = _compile_tree(test_dir, "test")
    if error is not None:
        print(error, file=sys.stderr)
        return 1
    sys.path.insert(0, str(root))
    try:
        module = importlib.import_module(package)
        for info in pkgutil.walk_packages(module.__path__, module.__name__ + "."):
            importlib.import_module(info.name)
    except Exception:
        traceback.print_exc()
        return 1
    print("BUILD OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
