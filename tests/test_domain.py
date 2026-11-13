import uuid

import pytest

from integrity.core.ids import human_code, new_id, uuid7
from integrity.domain.enums import EvaluationStatus as S
from integrity.domain.evaluation_state import TERMINAL, InvalidTransition, assert_transition, can_transition


@pytest.mark.parametrize("a,b", [(S.PENDING, S.QUEUED), (S.QUEUED, S.PROCESSING), (S.PROCESSING, S.COMPLETED),
                                 (S.PROCESSING, S.PARTIALLY_COMPLETED), (S.QUEUED, S.CANCELLED)])
def test_allowed_transitions(a, b):
    assert can_transition(a, b)


@pytest.mark.parametrize("a,b", [(S.PENDING, S.COMPLETED), (S.COMPLETED, S.PROCESSING), (S.FAILED, S.QUEUED),
                                 (S.CANCELLED, S.PROCESSING), (S.PROCESSING, S.PENDING)])
def test_forbidden_transitions(a, b):
    with pytest.raises(InvalidTransition):
        assert_transition(a, b)


def test_terminal_states_have_no_exit():
    for t in TERMINAL:
        assert not any(can_transition(t, other) for other in S)


def test_uuid7_format_and_order():
    a = uuid7()
    assert a.version == 7 and a.variant == uuid.RFC_4122
    ids = [new_id() for _ in range(50)]
    assert len(set(ids)) == 50
    # time-ordered at millisecond resolution: prefix (48-bit ts) is non-decreasing
    stamps = [int(i.replace("-", "")[:12], 16) for i in ids]
    assert stamps == sorted(stamps)


def test_human_code_alphabet():
    c = human_code()
    assert len(c) == 16 and not set(c) & set("ILOU01")
