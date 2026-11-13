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
                if mod.startswith(forbidden):
                    violations.append(f"{f.relative_to(PKG)} imports {mod}")
    assert not violations, violations


def test_no_heavy_imports_anywhere():
    heavy = ("torch", "transformers", "tensorflow", "spacy", "sentence_transformers", "numpy", "pandas")
    found = [f"{f.relative_to(PKG)}: {m}" for f in PKG.rglob("*.py") for m in _imports(f) if m.split(".")[0] in heavy]
    assert not found, found
