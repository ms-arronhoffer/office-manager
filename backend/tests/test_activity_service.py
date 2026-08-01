import datetime
import decimal
import enum
import json
import uuid

from app.services.activity_service import compute_changes


class _Status(enum.Enum):
    OPEN = "open"


def test_unchanged_values_produce_no_entry():
    assert compute_changes({"a": 1}, {"a": 1}) is None


def test_changes_are_json_serializable():
    """Regression: `changes` is a JSONB column, so every value must survive
    json.dumps. Raw datetime/Decimal values previously raised a TypeError on
    insert, which surfaced as "Failed to update ticket" after the update had
    already committed."""
    old = {
        "scheduled_date": datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc),
        "lease_expiration": datetime.date(2027, 1, 31),
        "assigned_to_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "rent_amount": decimal.Decimal("1200.50"),
        "status": _Status.OPEN,
        "tags": ["a", uuid.UUID("22222222-2222-2222-2222-222222222222")],
    }
    new = {
        "scheduled_date": datetime.datetime(2026, 9, 1),
        "lease_expiration": datetime.date(2028, 1, 31),
        "assigned_to_id": uuid.UUID("33333333-3333-3333-3333-333333333333"),
        "rent_amount": decimal.Decimal("1300.00"),
        "status": "closed",
        "tags": [],
    }

    changes = compute_changes(old, new)
    json.dumps(changes)  # must not raise

    assert changes["scheduled_date"]["old"] == "2026-08-01T00:00:00+00:00"
    assert changes["lease_expiration"]["new"] == "2028-01-31"
    assert changes["assigned_to_id"]["new"] == "33333333-3333-3333-3333-333333333333"
    # str, not float, so money keeps its exact value.
    assert changes["rent_amount"]["old"] == "1200.50"
    assert changes["status"]["old"] == "open"
    assert changes["tags"]["old"] == ["a", "22222222-2222-2222-2222-222222222222"]


def test_unknown_types_fall_back_to_string():
    class Weird:
        def __repr__(self):
            return "<weird>"

    changes = compute_changes({"w": None}, {"w": Weird()})
    json.dumps(changes)  # must not raise
    assert changes["w"]["new"] == "<weird>"
