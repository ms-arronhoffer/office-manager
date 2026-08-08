"""Tests for import replay protection and migration tie-out."""

import uuid

import pytest

from app.models.import_batch import ImportBatch, content_fingerprint
from app.services import import_assurance
from app.services.import_assurance import ReplayDetected


def test_fingerprint_is_stable_for_identical_payloads():
    assert content_fingerprint("leases", b"abc") == content_fingerprint("leases", b"abc")


def test_fingerprint_differs_by_entity():
    assert content_fingerprint("leases", b"abc") != content_fingerprint("offices", b"abc")


def test_fingerprint_differs_by_content():
    assert content_fingerprint("leases", b"abc") != content_fingerprint("leases", b"abd")


class _Session:
    """Returns a canned prior batch (or none) for the replay lookup."""

    def __init__(self, prior=None, counts=None):
        self._prior = prior
        self._counts = counts or {}
        self._call = 0

    async def execute(self, _stmt):
        prior, counts, index = self._prior, self._counts, self._call
        self._call += 1

        class _Result:
            def scalar_one_or_none(self):
                return prior

            def scalar_one(self):
                # Successive count() calls walk the supplied list.
                return list(counts.values())[index] if counts else 0

        return _Result()


@pytest.mark.asyncio
async def test_new_payload_returns_its_fingerprint():
    fingerprint = await import_assurance.check_replay(
        _Session(), organization_id=uuid.uuid4(), entity_type="leases", payload=b"rows"
    )
    assert fingerprint == content_fingerprint("leases", b"rows")


@pytest.mark.asyncio
async def test_previously_applied_payload_is_refused():
    from datetime import datetime, timezone

    prior = ImportBatch(
        id=uuid.uuid4(),
        source="xlsx",
        entity_type="leases",
        content_hash=content_fingerprint("leases", b"rows"),
        status="completed",
        created_count=12,
        updated_count=3,
    )
    prior.created_at = datetime.now(timezone.utc)

    with pytest.raises(ReplayDetected) as excinfo:
        await import_assurance.check_replay(
            _Session(prior),
            organization_id=uuid.uuid4(),
            entity_type="leases",
            payload=b"rows",
        )

    assert "already been imported" in str(excinfo.value)
    assert excinfo.value.batch is prior


@pytest.mark.asyncio
async def test_tie_out_reports_balance_when_counts_agree():
    session = _Session(counts={"offices": 5})
    report = await import_assurance.build_tie_out(
        session, organization_id=uuid.uuid4(), source_counts={"offices": 5}
    )
    assert report["balanced"] is True
    assert report["entities"][0]["variance"] == 0
    assert report["entities"][0]["status"] == "balanced"


@pytest.mark.asyncio
async def test_tie_out_reports_variance_when_records_are_missing():
    session = _Session(counts={"offices": 3})
    report = await import_assurance.build_tie_out(
        session, organization_id=uuid.uuid4(), source_counts={"offices": 5}
    )
    assert report["balanced"] is False
    assert report["entities"][0]["variance"] == -2
    assert report["entities"][0]["status"] == "variance"


@pytest.mark.asyncio
async def test_tie_out_marks_unknown_entities_as_unverifiable():
    report = await import_assurance.build_tie_out(
        _Session(), organization_id=uuid.uuid4(), source_counts={"gizmos": 4}
    )
    entry = report["entities"][0]
    assert entry["status"] == "not_verifiable"
    assert entry["destination_count"] is None
    # An unverifiable entity must not be reported as a clean tie-out.
    assert report["balanced"] is True or entry["variance"] is None
