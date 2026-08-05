"""New leases default to Active so missing status cannot suppress billing."""
from app.routers.leasing import ResidentLeaseCreate
from app.schemas.lease import LeaseCreate


def test_commercial_lease_create_defaults_active():
    payload = LeaseCreate(lease_name="Default Active", expiration_year=2030)
    assert payload.status == "active"


def test_residential_lease_create_defaults_active():
    import uuid

    payload = ResidentLeaseCreate(unit_id=uuid.uuid4())
    assert payload.status == "active"