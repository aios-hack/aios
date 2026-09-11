from backend.core.contracts import (
    Availability,
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    OperatingStatus,
    Role,
    WellState,
    canonical_bytes,
    canonical_schedule_hash,
    content_hash,
)


def _sample_prefix():
    return {
        "42": WellState(
            availability=Availability.AVAILABLE,
            role=Role.PROD,
            operating_status=OperatingStatus.OPEN,
            setpoint=20.0,
        )
    }


def test_canonical_schedule_hash_is_64_hex_chars() -> None:
    h = canonical_schedule_hash(_sample_prefix(), [], [])
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_canonical_schedule_hash_deterministic() -> None:
    prefix = _sample_prefix()
    fixed = [FixedDeckEvent(control_step=0, well="12", operator="COMPDATMD", raw_args=("1*", "1137.1"))]
    control = [ControlEvent(control_step=0, well="42", kind=EventKind.SET_LRAT, value=20.0)]
    h1 = canonical_schedule_hash(prefix, fixed, control)
    h2 = canonical_schedule_hash(_sample_prefix(), list(fixed), list(control))
    assert h1 == h2


def test_canonical_schedule_hash_changes_with_control_events() -> None:
    prefix = _sample_prefix()
    h1 = canonical_schedule_hash(prefix, [], [])
    h2 = canonical_schedule_hash(
        prefix, [], [ControlEvent(control_step=0, well="42", kind=EventKind.SHUT)]
    )
    assert h1 != h2


def test_canonical_bytes_key_order_does_not_matter() -> None:
    a = canonical_bytes({"b": 1, "a": 2})
    b = canonical_bytes({"a": 2, "b": 1})
    assert a == b


def test_content_hash_is_raw_sha256_not_jcs() -> None:
    raw = b"WCONPROD\n '42' 'OPEN' 'LRAT' 1* 1* 1* 20.0 1* 50 1* 1* /\n"
    h = content_hash(raw)
    assert len(h) == 64
    # разные байты -> разный хеш, без разбора/канонизации содержимого
    assert content_hash(raw + b" ") != h
