"""Import graph audit test.

Phase 9D: Ensures that gameplay_recorder's source tree only imports from:
  - Python standard library
  - Dependencies declared in pyproject.toml
  - Internal gameplay_recorder.* modules

Any other import (e.g. a private consumer system's packages) triggers a
test failure.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
_SRC_ROOT = _REPO_ROOT / "src" / "gameplay_recorder"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"

# Internal package prefix — imports starting with this are always allowed
_INTERNAL_PREFIX = "gameplay_recorder"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_declared_dependencies(pyproject_path: Path) -> set[str]:
    """Read pyproject.toml and return the set of top-level package names.

    Parses [project].dependencies and [project.optional-dependencies].dev.
    Extracts the base package name (e.g. "PySide6>=6.6" -> "pyside6").

    Returns a set of lower-cased package names for comparison.
    """
    with pyproject_path.open("rb") as fh:
        data = tomllib.load(fh)

    project = data.get("project", {})
    deps: list[str] = list(project.get("dependencies", []))

    optional = project.get("optional-dependencies", {})
    for group_deps in optional.values():
        deps.extend(group_deps)

    result: set[str] = set()
    for dep in deps:
        # Strip version specifiers: "PySide6>=6.6" -> "PySide6"
        base = dep.split(">=")[0].split("<=")[0].split("!=")[0].split("==")[0]
        base = base.split(">")[0].split("<")[0].split("[")[0].strip()
        # Normalize: PySide6 -> pyside6, adbutils -> adbutils
        result.add(base.lower().replace("-", "_"))

    return result


def _get_stdlib_modules() -> set[str]:
    """Return the set of standard-library top-level module names."""
    return sys.stdlib_module_names  # type: ignore[attr-defined]


def _extract_top_level_imports(source: str) -> list[str]:
    """Parse Python source and return all top-level imported module names.

    Handles both:
      import foo
      import foo.bar
      from foo import bar
      from foo.bar import baz
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # "import foo.bar" -> top-level is "foo"
                imports.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                # "from foo.bar import baz" -> top-level is "foo"
                imports.append(node.module.split(".")[0])
            # Relative imports (node.level > 0) are always internal — skip
    return imports


def _collect_py_files(root: Path) -> list[Path]:
    """Return all .py files under root, excluding __pycache__."""
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


def test_no_forbidden_imports_in_src() -> None:
    """gameplay_recorder must only import stdlib, declared deps, or itself.

    Walks every .py file in src/gameplay_recorder/, extracts import
    statements, and asserts that every top-level import is one of:
      - Python standard library module
      - A dependency declared in pyproject.toml
      - Internal: gameplay_recorder.*

    Any other import fails the test.
    """
    stdlib = _get_stdlib_modules()
    declared = _get_declared_dependencies(_PYPROJECT)
    py_files = _collect_py_files(_SRC_ROOT)

    violations: list[dict[str, object]] = []

    for path in sorted(py_files):
        source = path.read_text(encoding="utf-8", errors="replace")
        for top_level in _extract_top_level_imports(source):
            name_lower = top_level.lower().replace("-", "_")
            is_stdlib = top_level in stdlib
            is_internal = top_level == _INTERNAL_PREFIX or top_level.startswith(
                _INTERNAL_PREFIX + "."
            )
            is_declared = name_lower in declared

            if not (is_stdlib or is_internal or is_declared):
                violations.append(
                    {
                        "file": str(path.relative_to(_REPO_ROOT)),
                        "import": top_level,
                    }
                )

    if violations:
        lines = [f"  {v['file']}: imports {v['import']!r}" for v in violations]
        report = "\n".join(lines)
        raise AssertionError(
            f"Found {len(violations)} undeclared import(s) in gameplay_recorder source:\n"
            f"{report}\n\n"
            "Add missing packages to pyproject.toml [project].dependencies, "
            "or remove the import."
        )

    # Sanity: we scanned at least some files
    assert len(py_files) > 0, f"Expected .py files in {_SRC_ROOT}, found none"
