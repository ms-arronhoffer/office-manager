"""Orchestrates the ordered, idempotent migration of Buildium data into
Portfolio Desk's residential/financial domain models.

Each ``migrate_*`` function pulls one Buildium entity type, normalizes it, and
upserts it keyed by :class:`~app.models.buildium.BuildiumEntityMap` so re-runs
are safe (existing rows are updated, not duplicated). Functions are called in
dependency order by :func:`run_migration` (properties before units, owners
before owner-property links, etc.) so foreign keys always resolve.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_account import BankAccount
from app.models.buildium import BuildiumEntityMap, BuildiumGLAccountMap
from app.models.general_ledger import GLAccount
from app.models.maintenance_ticket import MaintenanceTicket, TicketCategory
from app.models.office import Office
from app.models.owner import OwnerProperty, PropertyOwner
from app.models.resident import RentalUnit, Resident, ResidentLease, ResidentLeaseOccupant
from app.models.vendor import Vendor
from app.models.vendor_bill import VendorBill, VendorBillLine
from app.services.buildium.client import BuildiumApiError, BuildiumClient
from app.services import ap_service
from app.services.ap_service import APError
from app.services.gl_service import GLError

logger = logging.getLogger(__name__)


# ── shared helpers ────────────────────────────────────────────────────────

def safe_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def safe_decimal(val: Any) -> Decimal | None:
    if val is None or val == "":
        return None
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        return None


def safe_date(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[: len(fmt) + 6], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


class MigrationResult:
    """Per-entity-type counters, mirroring ``import_service.ImportResult``."""

    def __init__(self):
        self.created = 0
        self.updated = 0
        self.skipped = 0
        self.errors: list[str] = []

    def to_dict(self) -> dict:
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors,
        }


async def _get_local_id(
    db: AsyncSession, organization_id: uuid.UUID, entity_type: str, buildium_id: Any
) -> uuid.UUID | None:
    row = (
        await db.execute(
            select(BuildiumEntityMap).where(
                BuildiumEntityMap.organization_id == organization_id,
                BuildiumEntityMap.entity_type == entity_type,
                BuildiumEntityMap.buildium_id == str(buildium_id),
            )
        )
    ).scalar_one_or_none()
    return row.local_id if row else None


async def _upsert_map(
    db: AsyncSession,
    organization_id: uuid.UUID,
    entity_type: str,
    buildium_id: Any,
    local_id: uuid.UUID,
    payload: dict | None = None,
) -> None:
    row = (
        await db.execute(
            select(BuildiumEntityMap).where(
                BuildiumEntityMap.organization_id == organization_id,
                BuildiumEntityMap.entity_type == entity_type,
                BuildiumEntityMap.buildium_id == str(buildium_id),
            )
        )
    ).scalar_one_or_none()
    phash = _payload_hash(payload) if payload is not None else None
    if row is None:
        db.add(
            BuildiumEntityMap(
                organization_id=organization_id,
                entity_type=entity_type,
                buildium_id=str(buildium_id),
                local_id=local_id,
                payload_hash=phash,
                last_synced_at=datetime.utcnow(),
            )
        )
    else:
        row.local_id = local_id
        row.payload_hash = phash
        row.last_synced_at = datetime.utcnow()


async def _next_office_number(db: AsyncSession, organization_id: uuid.UUID) -> int:
    existing = (
        await db.execute(select(Office.office_number).where(Office.organization_id == organization_id))
    ).scalars().all()
    return (max(existing) + 1) if existing else 1


# ── entity migrators ───────────────────────────────────────────────────────

async def migrate_properties(
    db: AsyncSession, organization_id: uuid.UUID, client: BuildiumClient, *, dry_run: bool
) -> MigrationResult:
    result = MigrationResult()
    async for item in client.list_properties():
        buildium_id = item.get("Id")
        try:
            addr = item.get("Address") or {}
            local_id = await _get_local_id(db, organization_id, "property", buildium_id)
            office = None
            if local_id:
                office = await db.get(Office, local_id)
            is_new = office is None
            if office is None:
                office = Office(
                    organization_id=organization_id,
                    office_number=await _next_office_number(db, organization_id),
                    location_type="property",
                    location_name=safe_str(item.get("Name")) or f"Buildium Property {buildium_id}",
                )
                db.add(office)
            office.location_name = safe_str(item.get("Name")) or office.location_name
            office.is_active = bool(item.get("IsActive", True))
            office.address_line_1 = safe_str(addr.get("AddressLine1"))
            office.address_line_2 = safe_str(addr.get("AddressLine2"))
            office.city = safe_str(addr.get("City"))
            office.state = (safe_str(addr.get("State")) or "")[:2] or None
            office.zip_code = safe_str(addr.get("PostalCode"))
            office.sector = safe_str(item.get("RentalSubType") or item.get("PropertyType"))
            if not dry_run:
                await db.flush()
                await _upsert_map(db, organization_id, "property", buildium_id, office.id, item)
            if is_new:
                result.created += 1
            else:
                result.updated += 1
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"property {buildium_id}: {exc}")
    if not dry_run:
        await db.commit()
    else:
        await db.rollback()
    return result


async def migrate_units(
    db: AsyncSession, organization_id: uuid.UUID, client: BuildiumClient, *, dry_run: bool
) -> MigrationResult:
    result = MigrationResult()
    property_ids = (
        await db.execute(
            select(BuildiumEntityMap.buildium_id, BuildiumEntityMap.local_id).where(
                BuildiumEntityMap.organization_id == organization_id,
                BuildiumEntityMap.entity_type == "property",
            )
        )
    ).all()
    for buildium_property_id, office_id in property_ids:
        async for item in client.list_units(buildium_property_id):
            buildium_id = item.get("Id")
            try:
                local_id = await _get_local_id(db, organization_id, "unit", buildium_id)
                unit = await db.get(RentalUnit, local_id) if local_id else None
                is_new = unit is None
                if unit is None:
                    unit = RentalUnit(
                        organization_id=organization_id,
                        office_id=office_id,
                        unit_number=safe_str(item.get("UnitNumber")) or str(buildium_id),
                    )
                    db.add(unit)
                unit.unit_number = safe_str(item.get("UnitNumber")) or unit.unit_number
                unit.market_rent = safe_decimal((item.get("MarketRent") or {}).get("Amount")) \
                    if isinstance(item.get("MarketRent"), dict) else safe_decimal(item.get("MarketRent"))
                unit.bedrooms = item.get("UnitBedrooms")
                unit.bathrooms = safe_decimal(item.get("UnitBathrooms"))
                unit.square_feet = safe_decimal(item.get("UnitSize"))
                if not dry_run:
                    await db.flush()
                    await _upsert_map(db, organization_id, "unit", buildium_id, unit.id, item)
                if is_new:
                    result.created += 1
                else:
                    result.updated += 1
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"unit {buildium_id}: {exc}")
    if not dry_run:
        await db.commit()
    else:
        await db.rollback()
    return result


async def migrate_owners(
    db: AsyncSession, organization_id: uuid.UUID, client: BuildiumClient, *, dry_run: bool
) -> MigrationResult:
    result = MigrationResult()
    async for item in client.list_owners():
        buildium_id = item.get("Id")
        try:
            local_id = await _get_local_id(db, organization_id, "owner", buildium_id)
            owner = await db.get(PropertyOwner, local_id) if local_id else None
            is_new = owner is None
            name = safe_str(item.get("CompanyName")) or " ".join(
                filter(None, [safe_str(item.get("FirstName")), safe_str(item.get("LastName"))])
            ) or f"Buildium Owner {buildium_id}"
            if owner is None:
                owner = PropertyOwner(organization_id=organization_id, name=name)
                db.add(owner)
            owner.name = name
            owner.owner_type = "company" if item.get("IsCompany") else "individual"
            owner.first_name = safe_str(item.get("FirstName"))
            owner.last_name = safe_str(item.get("LastName"))
            owner.email = safe_str((item.get("Email")))
            owner.tax_id = safe_str(item.get("TaxId"))
            owner.management_fee_percent = safe_decimal(item.get("ManagementAgreement", {}).get("ManagementFeePercent")) \
                if isinstance(item.get("ManagementAgreement"), dict) else owner.management_fee_percent
            if not dry_run:
                await db.flush()
                await _upsert_map(db, organization_id, "owner", buildium_id, owner.id, item)
            if is_new:
                result.created += 1
            else:
                result.updated += 1

            # Owner-property links, when Buildium includes a Properties array.
            for prop in item.get("Properties") or []:
                bld_property_id = prop.get("PropertyId") or prop.get("Id")
                office_id = await _get_local_id(db, organization_id, "property", bld_property_id)
                if office_id is None:
                    continue
                existing_link = (
                    await db.execute(
                        select(OwnerProperty).where(
                            OwnerProperty.owner_id == owner.id,
                            OwnerProperty.office_id == office_id,
                        )
                    )
                ).scalar_one_or_none()
                if existing_link is None and not dry_run:
                    db.add(
                        OwnerProperty(
                            organization_id=organization_id,
                            owner_id=owner.id,
                            office_id=office_id,
                            ownership_percent=safe_decimal(prop.get("OwnershipPercentage")) or Decimal("100"),
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"owner {buildium_id}: {exc}")
    if not dry_run:
        await db.commit()
    else:
        await db.rollback()
    return result


async def migrate_vendors(
    db: AsyncSession, organization_id: uuid.UUID, client: BuildiumClient, *, dry_run: bool
) -> MigrationResult:
    result = MigrationResult()
    async for item in client.list_vendors():
        buildium_id = item.get("Id")
        try:
            local_id = await _get_local_id(db, organization_id, "vendor", buildium_id)
            vendor = await db.get(Vendor, local_id) if local_id else None
            is_new = vendor is None
            company_name = safe_str(item.get("Name") or item.get("CompanyName")) or f"Buildium Vendor {buildium_id}"
            if vendor is None:
                vendor = Vendor(organization_id=organization_id, company_name=company_name)
                db.add(vendor)
            vendor.company_name = company_name
            vendor.contact_email = safe_str(item.get("Email"))
            vendor.contact_phone = safe_str(item.get("PhoneNumber"))
            vendor.tax_id = safe_str(item.get("TaxId"))
            vendor.is_1099_vendor = bool(item.get("Is1099Eligible") or item.get("Include1099"))
            if not dry_run:
                await db.flush()
                await _upsert_map(db, organization_id, "vendor", buildium_id, vendor.id, item)
            if is_new:
                result.created += 1
            else:
                result.updated += 1
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"vendor {buildium_id}: {exc}")
    if not dry_run:
        await db.commit()
    else:
        await db.rollback()
    return result


async def migrate_tenants(
    db: AsyncSession, organization_id: uuid.UUID, client: BuildiumClient, *, dry_run: bool
) -> MigrationResult:
    result = MigrationResult()
    async for item in client.list_tenants():
        buildium_id = item.get("Id")
        try:
            local_id = await _get_local_id(db, organization_id, "tenant", buildium_id)
            resident = await db.get(Resident, local_id) if local_id else None
            is_new = resident is None
            first_name = safe_str(item.get("FirstName")) or "Unknown"
            last_name = safe_str(item.get("LastName")) or f"Tenant {buildium_id}"
            if resident is None:
                resident = Resident(
                    organization_id=organization_id, first_name=first_name, last_name=last_name,
                )
                db.add(resident)
            resident.first_name = first_name
            resident.last_name = last_name
            resident.email = safe_str(item.get("Email"))
            resident.phone = safe_str((item.get("PhoneNumbers") or [{}])[0].get("Number")) \
                if item.get("PhoneNumbers") else safe_str(item.get("PhoneNumber"))
            if not dry_run:
                await db.flush()
                await _upsert_map(db, organization_id, "tenant", buildium_id, resident.id, item)
            if is_new:
                result.created += 1
            else:
                result.updated += 1
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"tenant {buildium_id}: {exc}")
    if not dry_run:
        await db.commit()
    else:
        await db.rollback()
    return result


async def migrate_leases(
    db: AsyncSession, organization_id: uuid.UUID, client: BuildiumClient, *, dry_run: bool
) -> MigrationResult:
    result = MigrationResult()
    occupant_result = MigrationResult()
    async for item in client.list_leases():
        buildium_id = item.get("Id")
        try:
            unit_id = await _get_local_id(db, organization_id, "unit", item.get("UnitId"))
            if unit_id is None:
                result.errors.append(f"lease {buildium_id}: unit {item.get('UnitId')} not migrated yet")
                continue
            local_id = await _get_local_id(db, organization_id, "lease", buildium_id)
            lease = await db.get(ResidentLease, local_id) if local_id else None
            is_new = lease is None
            if lease is None:
                lease = ResidentLease(organization_id=organization_id, unit_id=unit_id)
                db.add(lease)
            lease.unit_id = unit_id
            lease.start_date = safe_date(item.get("LeaseFromDate"))
            lease.end_date = safe_date(item.get("LeaseToDate"))
            lease.rent_amount = safe_decimal((item.get("RentAmount") or {}).get("Amount")) \
                if isinstance(item.get("RentAmount"), dict) else safe_decimal(item.get("RentAmount"))
            raw_status = (safe_str(item.get("LeaseStatus")) or "").lower()
            lease.status = {
                "active": "active", "past": "ended", "future": "pending",
            }.get(raw_status, "draft")
            if not dry_run:
                await db.flush()
                await _upsert_map(db, organization_id, "lease", buildium_id, lease.id, item)
            if is_new:
                result.created += 1
            else:
                result.updated += 1

            for tenant_ref in item.get("Tenants") or []:
                tenant_buildium_id = tenant_ref.get("Id")
                resident_id = await _get_local_id(db, organization_id, "tenant", tenant_buildium_id)
                if resident_id is None:
                    occupant_result.errors.append(
                        f"lease {buildium_id}: tenant {tenant_buildium_id} not migrated yet"
                    )
                    continue
                existing_occupant = (
                    await db.execute(
                        select(ResidentLeaseOccupant).where(
                            ResidentLeaseOccupant.lease_id == lease.id,
                            ResidentLeaseOccupant.resident_id == resident_id,
                        )
                    )
                ).scalar_one_or_none()
                if existing_occupant is None:
                    if not dry_run:
                        db.add(
                            ResidentLeaseOccupant(
                                lease_id=lease.id, resident_id=resident_id, role="primary",
                            )
                        )
                    occupant_result.created += 1
                else:
                    occupant_result.updated += 1
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"lease {buildium_id}: {exc}")
    if not dry_run:
        await db.commit()
    else:
        await db.rollback()
    return result, occupant_result


async def migrate_bank_accounts(
    db: AsyncSession, organization_id: uuid.UUID, client: BuildiumClient, *, dry_run: bool
) -> MigrationResult:
    result = MigrationResult()
    async for item in client.list_bank_accounts():
        buildium_id = item.get("Id")
        try:
            local_id = await _get_local_id(db, organization_id, "bank_account", buildium_id)
            account = await db.get(BankAccount, local_id) if local_id else None
            is_new = account is None
            name = safe_str(item.get("Name")) or f"Buildium Bank {buildium_id}"
            if account is None:
                account = BankAccount(organization_id=organization_id, name=name)
                db.add(account)
            account.name = name
            account.institution = safe_str(item.get("BankAccountType"))
            last4 = safe_str(item.get("AccountNumber"))
            account.account_number_last4 = last4[-4:] if last4 else None
            account.is_active = not bool(item.get("IsActive") is False)
            if not dry_run:
                await db.flush()
                await _upsert_map(db, organization_id, "bank_account", buildium_id, account.id, item)
            if is_new:
                result.created += 1
            else:
                result.updated += 1
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"bank_account {buildium_id}: {exc}")
    if not dry_run:
        await db.commit()
    else:
        await db.rollback()
    return result


# Buildium account types -> Portfolio Desk ACCOUNT_TYPES.
_GL_TYPE_MAP = {
    "asset": "asset", "liability": "liability", "equity": "equity",
    "income": "revenue", "revenue": "revenue", "expense": "expense",
}


async def migrate_gl_accounts(
    db: AsyncSession, organization_id: uuid.UUID, client: BuildiumClient, *, dry_run: bool
) -> MigrationResult:
    result = MigrationResult()
    async for item in client.list_gl_accounts():
        buildium_id = item.get("Id")
        try:
            existing_map = (
                await db.execute(
                    select(BuildiumGLAccountMap).where(
                        BuildiumGLAccountMap.organization_id == organization_id,
                        BuildiumGLAccountMap.buildium_gl_account_id == str(buildium_id),
                    )
                )
            ).scalar_one_or_none()
            account = await db.get(GLAccount, existing_map.gl_account_id) if existing_map and existing_map.gl_account_id else None
            is_new = account is None
            name = safe_str(item.get("Name")) or f"Buildium Account {buildium_id}"
            acct_type = _GL_TYPE_MAP.get((safe_str(item.get("Type")) or "").lower(), "expense")
            if account is None:
                code = safe_str(item.get("AccountNumber")) or f"BLD-{buildium_id}"
                account = GLAccount(
                    organization_id=organization_id, code=code, name=name, type=acct_type,
                )
                db.add(account)
            account.name = name
            account.type = acct_type
            if not dry_run:
                await db.flush()
                if existing_map is None:
                    db.add(
                        BuildiumGLAccountMap(
                            organization_id=organization_id,
                            buildium_gl_account_id=str(buildium_id),
                            buildium_account_name=name,
                            buildium_account_type=acct_type,
                            gl_account_id=account.id,
                            auto_created=True,
                        )
                    )
                else:
                    existing_map.gl_account_id = account.id
                    existing_map.buildium_account_name = name
                    existing_map.buildium_account_type = acct_type
            if is_new:
                result.created += 1
            else:
                result.updated += 1
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"gl_account {buildium_id}: {exc}")
    if not dry_run:
        await db.commit()
    else:
        await db.rollback()
    return result


async def migrate_bills(
    db: AsyncSession, organization_id: uuid.UUID, client: BuildiumClient, *, dry_run: bool,
    posted_by_id: uuid.UUID | None = None,
) -> MigrationResult:
    result = MigrationResult()
    async for item in client.list_bills():
        buildium_id = item.get("Id")
        try:
            vendor_id = await _get_local_id(db, organization_id, "vendor", item.get("VendorId"))
            if vendor_id is None:
                result.errors.append(f"bill {buildium_id}: vendor {item.get('VendorId')} not migrated yet")
                continue
            local_id = await _get_local_id(db, organization_id, "bill", buildium_id)
            bill = await db.get(VendorBill, local_id) if local_id else None
            is_new = bill is None
            if bill is not None and bill.status == "finalized":
                # Immutable once finalized/posted — skip re-import.
                result.skipped += 1
                continue
            if bill is None:
                bill = VendorBill(
                    organization_id=organization_id,
                    vendor_id=vendor_id,
                    bill_date=safe_date(item.get("Date")) or date.today(),
                )
                db.add(bill)
            bill.vendor_id = vendor_id
            bill.bill_date = safe_date(item.get("Date")) or bill.bill_date
            bill.due_date = safe_date(item.get("DueDate"))
            bill.bill_number = safe_str(item.get("ReferenceNumber"))
            bill.memo = safe_str(item.get("Memo"))

            bill.lines.clear()
            total = Decimal("0")
            for idx, line in enumerate(item.get("Lines") or [], start=1):
                gl_account_id = await _get_local_id(
                    db, organization_id, "gl_account", line.get("GLAccountId")
                )
                if gl_account_id is None:
                    continue
                amount = safe_decimal(line.get("Amount")) or Decimal("0")
                if amount <= 0:
                    continue
                bill.lines.append(
                    VendorBillLine(
                        account_id=gl_account_id, line_number=idx,
                        description=safe_str(line.get("Memo")), amount=amount,
                    )
                )
                total += amount
            bill.total_amount = total

            if not dry_run:
                await db.flush()
                await _upsert_map(db, organization_id, "bill", buildium_id, bill.id, item)
                if total > 0 and bill.status == "draft":
                    bill.status = "finalized"
                    bill.finalized_at = datetime.utcnow()
                    bill.finalized_by_id = posted_by_id
                    await db.flush()
                    try:
                        await ap_service.post_bill_to_gl(
                            db, organization_id, bill, posted_by_id=posted_by_id
                        )
                    except (APError, GLError) as exc:
                        # Common cause: the bill date falls in a closed period.
                        result.errors.append(f"bill {buildium_id}: GL posting skipped ({exc})")
            if is_new:
                result.created += 1
            else:
                result.updated += 1
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"bill {buildium_id}: {exc}")
    if not dry_run:
        await db.commit()
    else:
        await db.rollback()
    return result


async def migrate_tasks(
    db: AsyncSession, organization_id: uuid.UUID, client: BuildiumClient, *, dry_run: bool,
    created_by_id: uuid.UUID | None = None,
) -> MigrationResult:
    result = MigrationResult()
    if created_by_id is None:
        result.errors.append("tasks: no user available to attribute imported tickets to; skipped")
        return result

    category = (
        await db.execute(
            select(TicketCategory).where(
                TicketCategory.organization_id == organization_id,
                TicketCategory.name == "Buildium Import",
            )
        )
    ).scalar_one_or_none()
    if category is None and not dry_run:
        category = TicketCategory(organization_id=organization_id, name="Buildium Import")
        db.add(category)
        await db.flush()

    async for item in client.list_tasks():
        buildium_id = item.get("Id")
        try:
            office_id = await _get_local_id(db, organization_id, "property", item.get("PropertyId"))
            if office_id is None or category is None:
                result.skipped += 1
                continue
            local_id = await _get_local_id(db, organization_id, "task", buildium_id)
            ticket = await db.get(MaintenanceTicket, local_id) if local_id else None
            is_new = ticket is None
            status_map = {"open": "open", "inprogress": "in_progress", "completed": "closed"}
            status = status_map.get((safe_str(item.get("Status")) or "").lower().replace(" ", ""), "open")
            if ticket is None:
                ticket = MaintenanceTicket(
                    organization_id=organization_id,
                    subject=safe_str(item.get("Subject")) or f"Buildium Task {buildium_id}",
                    priority=(safe_str(item.get("Priority")) or "medium").lower(),
                    category_id=category.id,
                    office_id=office_id,
                    description=safe_str(item.get("Description")) or "",
                    created_by_id=created_by_id,
                )
                db.add(ticket)
            ticket.subject = safe_str(item.get("Subject")) or ticket.subject
            ticket.status = status
            ticket.description = safe_str(item.get("Description")) or ticket.description
            if not dry_run:
                await db.flush()
                await _upsert_map(db, organization_id, "task", buildium_id, ticket.id, item)
            if is_new:
                result.created += 1
            else:
                result.updated += 1
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"task {buildium_id}: {exc}")
    if not dry_run:
        await db.commit()
    else:
        await db.rollback()
    return result


# ── orchestration ───────────────────────────────────────────────────────────

# (entity_type, label) in dependency order. "lease" produces two result sets
# (lease + occupant) so it is special-cased in run_migration.
ENTITY_STEPS: list[tuple[str, str]] = [
    ("property", "Properties"),
    ("unit", "Units"),
    ("gl_account", "GL Accounts"),
    ("owner", "Owners"),
    ("vendor", "Vendors"),
    ("tenant", "Tenants"),
    ("lease", "Leases"),
    ("bank_account", "Bank Accounts"),
    ("bill", "Bills"),
    ("task", "Tasks"),
]


async def run_migration(
    db: AsyncSession,
    organization_id: uuid.UUID,
    client: BuildiumClient,
    *,
    entities: list[str] | None = None,
    dry_run: bool = False,
    actor_id: uuid.UUID | None = None,
    on_progress: Callable[[str, dict], Awaitable[None]] | None = None,
) -> dict[str, dict]:
    """Run each requested entity migrator in dependency order, returning a
    ``{entity_type: {created, updated, skipped, errors}}`` progress map."""
    wanted = set(entities) if entities else None
    progress: dict[str, dict] = {}

    for entity_type, _label in ENTITY_STEPS:
        if wanted is not None and entity_type not in wanted:
            continue
        try:
            if entity_type == "property":
                res = await migrate_properties(db, organization_id, client, dry_run=dry_run)
                progress[entity_type] = res.to_dict()
            elif entity_type == "unit":
                res = await migrate_units(db, organization_id, client, dry_run=dry_run)
                progress[entity_type] = res.to_dict()
            elif entity_type == "gl_account":
                res = await migrate_gl_accounts(db, organization_id, client, dry_run=dry_run)
                progress[entity_type] = res.to_dict()
            elif entity_type == "owner":
                res = await migrate_owners(db, organization_id, client, dry_run=dry_run)
                progress[entity_type] = res.to_dict()
            elif entity_type == "vendor":
                res = await migrate_vendors(db, organization_id, client, dry_run=dry_run)
                progress[entity_type] = res.to_dict()
            elif entity_type == "tenant":
                res = await migrate_tenants(db, organization_id, client, dry_run=dry_run)
                progress[entity_type] = res.to_dict()
            elif entity_type == "lease":
                lease_res, occupant_res = await migrate_leases(db, organization_id, client, dry_run=dry_run)
                progress["lease"] = lease_res.to_dict()
                progress["lease_occupant"] = occupant_res.to_dict()
            elif entity_type == "bank_account":
                res = await migrate_bank_accounts(db, organization_id, client, dry_run=dry_run)
                progress[entity_type] = res.to_dict()
            elif entity_type == "bill":
                res = await migrate_bills(
                    db, organization_id, client, dry_run=dry_run, posted_by_id=actor_id
                )
                progress[entity_type] = res.to_dict()
            elif entity_type == "task":
                res = await migrate_tasks(
                    db, organization_id, client, dry_run=dry_run, created_by_id=actor_id
                )
                progress[entity_type] = res.to_dict()
        except BuildiumApiError as exc:
            logger.exception("Buildium API error migrating %s", entity_type)
            progress[entity_type] = {
                "created": 0, "updated": 0, "skipped": 0, "errors": [str(exc)],
            }
        if on_progress:
            await on_progress(entity_type, progress[entity_type])

    return progress
