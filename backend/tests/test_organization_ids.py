"""Organization identifiers must be random rather than enumerable."""
import uuid

from app.models.organization import new_organization_id


def test_new_organization_ids_are_unique_uuid4_values():
    identifiers = [new_organization_id() for _ in range(1_000)]

    assert len(set(identifiers)) == len(identifiers)
    assert all(isinstance(identifier, uuid.UUID) for identifier in identifiers)
    assert all(identifier.version == 4 for identifier in identifiers)
    assert uuid.UUID("00000000-0000-0000-0000-000000000001") not in identifiers