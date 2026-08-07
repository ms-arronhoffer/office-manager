"""Fixture-free scheduled resident autopay contract tests."""

import uuid
from types import SimpleNamespace

from app.tasks.resident_autopay import _attempt_key, _pending_blocks_new_debit
from app.tasks.scheduler import _JOBS


def test_attempt_key_is_stable_across_invoice_order():
    lease_id = uuid.uuid4()
    invoice_ids = [uuid.uuid4(), uuid.uuid4()]

    assert _attempt_key(lease_id, invoice_ids) == _attempt_key(
        lease_id, list(reversed(invoice_ids))
    )


def test_attempt_key_changes_when_due_invoice_set_changes():
    lease_id = uuid.uuid4()
    first_invoice = uuid.uuid4()

    assert _attempt_key(lease_id, [first_invoice]) != _attempt_key(
        lease_id, [first_invoice, uuid.uuid4()]
    )


def test_pending_processor_reference_blocks_another_scheduled_debit():
    assert _pending_blocks_new_debit(SimpleNamespace(processor_ref="ch_pending")) is True
    assert _pending_blocks_new_debit(SimpleNamespace(processor_ref=None)) is False
    assert _pending_blocks_new_debit(None) is False


def test_daily_resident_autopay_job_is_registered():
    job = next(job for job in _JOBS if job[0] == "resident_autopay")

    assert job[2] == "cron"
    assert job[3] == {"hour": 6, "minute": 15}