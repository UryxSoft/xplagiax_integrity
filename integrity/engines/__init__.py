"""Shared analysis engines.

An engine is a pure function ``run(StageInput) -> StageOutput``: no database,
no HTTP, no Flask. Workers load the inputs, call the engine and persist the
output. Enforced by tests/test_architecture.py.
"""
