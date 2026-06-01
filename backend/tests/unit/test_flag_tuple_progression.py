"""Unit tests for flag_tuple_progression — W5/PR5.4."""
import uuid
import pytest
from app.core.flag_tuple_progression import (
    PROGRESSION_ORDER,
    MAX_FLIP_SECONDS,
    cohort_percentage,
    resolve_tuple_for_session,
    adjacent_in_progression,
)


def test_cohort_percentage_in_range():
    for _ in range(100):
        sid = uuid.uuid4()
        result = cohort_percentage(sid)
        assert 0 <= result <= 99, f"out of range: {result} for {sid}"


def test_cohort_percentage_deterministic():
    sid = uuid.uuid4()
    first = cohort_percentage(sid)
    for _ in range(10):
        assert cohort_percentage(sid) == first


def test_resolve_tuple_baseline_when_percentage_zero():
    for _ in range(50):
        sid = uuid.uuid4()
        result = resolve_tuple_for_session(
            sid, baseline_tuple="T1", target_tuple="T2", active_percentage=0
        )
        assert result == "T1"


def test_resolve_tuple_target_when_percentage_100():
    for _ in range(50):
        sid = uuid.uuid4()
        result = resolve_tuple_for_session(
            sid, baseline_tuple="T1", target_tuple="T2", active_percentage=100
        )
        assert result == "T2"


def test_resolve_tuple_split_at_50():
    target_count = sum(
        1
        for _ in range(1000)
        if resolve_tuple_for_session(
            uuid.uuid4(), baseline_tuple="T1", target_tuple="T2", active_percentage=50
        )
        == "T2"
    )
    assert 450 <= target_count <= 550, f"expected ~500, got {target_count}"


def test_resolve_tuple_rejects_negative_percentage():
    with pytest.raises(ValueError, match="active_percentage must be in"):
        resolve_tuple_for_session(
            uuid.uuid4(), baseline_tuple="T1", target_tuple="T2", active_percentage=-1
        )


def test_resolve_tuple_rejects_over_100():
    with pytest.raises(ValueError, match="active_percentage must be in"):
        resolve_tuple_for_session(
            uuid.uuid4(), baseline_tuple="T1", target_tuple="T2", active_percentage=101
        )


def test_adjacent_in_progression_T1_T2():
    assert adjacent_in_progression("T1", "T2") is True
    assert adjacent_in_progression("T2", "T1") is True


def test_adjacent_in_progression_T3_T4():
    assert adjacent_in_progression("T3", "T4") is True
    assert adjacent_in_progression("T4", "T3") is True


def test_NOT_adjacent_T1_T3():
    assert adjacent_in_progression("T1", "T3") is False


def test_NOT_adjacent_T1_T4():
    assert adjacent_in_progression("T1", "T4") is False


def test_progression_order_is_exactly_four():
    assert PROGRESSION_ORDER == ["T1", "T2", "T3", "T4"]


def test_max_flip_seconds_is_ten_minutes():
    assert MAX_FLIP_SECONDS == 600
