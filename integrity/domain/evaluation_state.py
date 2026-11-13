"""Evaluation lifecycle state machine (pure)."""

from __future__ import annotations

from integrity.domain.enums import EvaluationStatus as S

TERMINAL: frozenset[S] = frozenset({S.COMPLETED, S.PARTIALLY_COMPLETED, S.FAILED, S.CANCELLED})

_ALLOWED: dict[S, frozenset[S]] = {
    S.PENDING: frozenset({S.QUEUED, S.CANCELLED, S.FAILED}),
    S.QUEUED: frozenset({S.PROCESSING, S.CANCELLED, S.FAILED}),
    S.PROCESSING: frozenset({S.COMPLETED, S.PARTIALLY_COMPLETED, S.FAILED, S.CANCELLED}),
}


class InvalidTransition(ValueError):
    pass


def can_transition(current: S, target: S) -> bool:
    return target in _ALLOWED.get(current, frozenset())


def assert_transition(current: S, target: S) -> None:
    if not can_transition(current, target):
        raise InvalidTransition(f"evaluation cannot go from {current.value} to {target.value}")
