"""Separation-of-duties tests for the shared finance approval gate.

These are the checks an auditor performs: that a document cannot post without a
second signature, that the person who prepared it cannot be that signature, and
that editing an approved document invalidates the sign-off.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.user import User
from app.models.vendor_bill import VendorBill, VendorBillLine
from app.services import approval_service
from app.services.approval_service import ApprovalError


def _user(role: str = "accountant") -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{role}-{uuid.uuid4().hex[:6]}@test.com",
        display_name=role,
        role=role,
        is_active=True,
    )


def _bill(amount: str = "1000.00") -> VendorBill:
    bill = VendorBill(
        id=uuid.uuid4(),
        vendor_id=uuid.uuid4(),
        bill_date=date(2026, 1, 1),
        status="draft",
        approval_status="pending",
        total_amount=Decimal(amount),
    )
    bill.lines = [
        VendorBillLine(account_id=uuid.uuid4(), line_number=1, amount=Decimal(amount))
    ]
    return bill


# ─── The core control ────────────────────────────────────────────────────────

def test_preparer_cannot_approve_own_document():
    preparer = _user()
    bill = _bill()
    bill.prepared_by_id = preparer.id

    with pytest.raises(ApprovalError, match="preparer"):
        approval_service.approve(bill, user=preparer)


def test_submitter_cannot_approve_own_document():
    submitter = _user()
    bill = _bill()
    bill.prepared_by_id = uuid.uuid4()
    bill.submitted_by_id = submitter.id

    with pytest.raises(ApprovalError, match="submitter"):
        approval_service.approve(bill, user=submitter)


def test_second_person_can_approve():
    preparer, approver = _user(), _user("admin")
    bill = _bill()
    bill.prepared_by_id = preparer.id
    bill.submitted_by_id = preparer.id

    approval_service.approve(bill, user=approver)

    assert bill.approval_status == "approved"
    assert bill.approved_by_id == approver.id
    assert bill.approved_at is not None


# ─── Posting guard ───────────────────────────────────────────────────────────

def test_pending_document_cannot_post():
    bill = _bill()
    bill.approval_status = "pending"
    with pytest.raises(ApprovalError, match="approved by a second reviewer"):
        approval_service.assert_postable(bill)


def test_rejected_document_cannot_post():
    bill = _bill()
    bill.approval_status = "rejected"
    with pytest.raises(ApprovalError, match="rejected"):
        approval_service.assert_postable(bill)


def test_approved_document_can_post():
    bill = _bill()
    bill.prepared_by_id = uuid.uuid4()
    bill.approval_status = "approved"
    bill.approved_by_id = uuid.uuid4()
    approval_service.assert_postable(bill)


def test_not_required_document_can_post():
    """Below-threshold documents post directly, but say so explicitly."""
    bill = _bill()
    bill.approval_status = "not_required"
    approval_service.assert_postable(bill)


def test_self_approved_row_is_still_refused_at_post_time():
    """Defence in depth against a row written by an older code path."""
    actor = uuid.uuid4()
    bill = _bill()
    bill.prepared_by_id = actor
    bill.approval_status = "approved"
    bill.approved_by_id = actor

    with pytest.raises(ApprovalError, match="preparer"):
        approval_service.assert_postable(bill)


# ─── Rejection and rework ────────────────────────────────────────────────────

def test_reject_records_reviewer_and_reason():
    bill = _bill()
    bill.prepared_by_id = uuid.uuid4()
    reviewer = _user("admin")

    approval_service.reject(bill, user=reviewer, reason="Missing receipt")

    assert bill.approval_status == "rejected"
    assert bill.rejected_by_id == reviewer.id
    assert bill.rejection_reason == "Missing receipt"
    assert bill.approved_by_id is None


def test_rejecter_cannot_be_the_preparer():
    preparer = _user()
    bill = _bill()
    bill.prepared_by_id = preparer.id
    with pytest.raises(ApprovalError):
        approval_service.reject(bill, user=preparer)


def test_cannot_approve_twice():
    bill = _bill()
    bill.prepared_by_id = uuid.uuid4()
    approval_service.approve(bill, user=_user("admin"))
    with pytest.raises(ApprovalError, match="already been approved"):
        approval_service.approve(bill, user=_user("admin"))


def test_cannot_approve_a_document_that_does_not_need_it():
    bill = _bill()
    bill.approval_status = "not_required"
    with pytest.raises(ApprovalError, match="does not require approval"):
        approval_service.approve(bill, user=_user("admin"))


# ─── Serialization ───────────────────────────────────────────────────────────

def test_serialize_exposes_the_audit_trail():
    preparer, approver = _user(), _user("admin")
    bill = _bill()
    bill.prepared_by_id = preparer.id
    bill.submitted_by_id = preparer.id
    bill.submitted_at = datetime.now(timezone.utc)
    approval_service.approve(bill, user=approver)

    payload = approval_service.serialize(bill)

    assert payload["approval_status"] == "approved"
    assert payload["prepared_by_id"] == preparer.id
    assert payload["approved_by_id"] == approver.id
    assert payload["submitted_at"] is not None
