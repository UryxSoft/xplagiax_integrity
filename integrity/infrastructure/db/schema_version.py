"""Expected Alembic head for this code version.

Kept as a constant so the web process never imports Alembic at runtime
(measured: ~11 MB RSS per worker). tests/test_migrations.py fails if this
drifts from the real head, so a new migration must bump it.
"""

EXPECTED_SCHEMA_HEADS: frozenset[str] = frozenset({"0001"})
