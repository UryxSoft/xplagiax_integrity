"""Import-boundary rules (cheap, dependency-free alternative to import-linter)."""

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "integrity"

RULES = {
    # layer: forbidden import prefixes
    "domain": ("flask", "sqlalchemy", "alembic", "werkzeug", "integrity.infrastructure", "integrity.api",
               "integrity.security", "integrity.core"),
    "infrastructure": ("integrity.api",),
    "core": ("integrity.api", "integrity.infrastructure", "integrity.security"),
    "security": ("integrity.api", "integrity.application"),
    "application": ("flask", "werkzeug", "integrity.api"),
}


def _imports(path: Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


def test_layer_boundaries():
    violations = []
    for layer, forbidden in RULES.items():
        for f in (PKG / layer).rglob("*.py"):
            if "migrations" in f.parts:
                continue
            for mod in _imports(f):
                if any(mod == p or mod.startswith(p + ".") for p in forbidden):
                    violations.append(f"{f.relative_to(PKG)} imports {mod}")
    assert not violations, violations


def test_no_relative_imports():
    """Relative imports would be invisible to the boundary rules above."""
    offenders = []
    for f in PKG.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level > 0:
                offenders.append(str(f.relative_to(PKG)))
    assert not offenders, offenders


def test_boundary_rules_detect_a_violation(tmp_path):
    """The checker itself must be able to fail."""
    bad = tmp_path / "bad.py"
    bad.write_text("from integrity.api.v1 import health\nimport sqlalchemy\n")
    assert [m for m in _imports(bad) if any(m == p or m.startswith(p + ".") for p in RULES["domain"])] == ["integrity.api.v1", "sqlalchemy"]


def test_no_heavy_imports_anywhere():
    heavy = ("torch", "transformers", "tensorflow", "spacy", "sentence_transformers", "numpy", "pandas")
    found = [f"{f.relative_to(PKG)}: {m}" for f in PKG.rglob("*.py") for m in _imports(f) if m.split(".")[0] in heavy]
    assert not found, found
