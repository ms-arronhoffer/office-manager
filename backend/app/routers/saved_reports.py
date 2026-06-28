"""Saved & scheduled reports API (Item 4A).

CRUD for reusable report definitions (:class:`SavedReport`) and their delivery
schedules (:class:`ReportSchedule`). Report definitions are validated against
the existing dataset/template engine (``DATASET_CONFIGS``) — only known
datasets, columns and filters are accepted; there is no free-form SQL.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.saved_report import REPORT_FORMATS, ReportSchedule, SavedReport
from app.models.user import User
from app.schemas.saved_report import (
    ReportScheduleCreate,
    ReportScheduleResponse,
    ReportScheduleUpdate,
    SavedReportCreate,
    SavedReportResponse,
    SavedReportUpdate,
)
from app.services.report_service import ReportSpecError, validate_report_spec
from app.utils.scheduling import SCHEDULE_FREQUENCIES, compute_next_run

router = APIRouter()


def _validate_spec_or_400(dataset: str, columns, filters) -> tuple:
    try:
        return validate_report_spec(dataset, columns, filters, strict=True)
    except ReportSpecError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _validate_format_or_400(fmt: str) -> str:
    if fmt not in REPORT_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{fmt}'. Use one of: {', '.join(REPORT_FORMATS)}",
        )
    return fmt


def _validate_frequency_or_400(freq: str) -> str:
    if freq not in SCHEDULE_FREQUENCIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported frequency '{freq}'. Use one of: {', '.join(SCHEDULE_FREQUENCIES)}",
        )
    return freq


async def _get_owned_report(db: AsyncSession, report_id: uuid.UUID, user: User) -> SavedReport:
    result = await db.execute(
        select(SavedReport).where(
            SavedReport.id == report_id,
            SavedReport.organization_id == user.organization_id,
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved report not found")
    return report


# ── Saved reports ──────────────────────────────────────────────────────────────

@router.get("", response_model=list[SavedReportResponse])
async def list_saved_reports(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SavedReport)
        .where(SavedReport.organization_id == user.organization_id)
        .order_by(SavedReport.name)
    )
    return [
        SavedReportResponse.model_validate(r, from_attributes=True)
        for r in result.scalars().all()
    ]


@router.post("", response_model=SavedReportResponse, status_code=status.HTTP_201_CREATED)
async def create_saved_report(
    payload: SavedReportCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "editor")),
):
    _validate_format_or_400(payload.format)
    dataset, columns, filters = _validate_spec_or_400(
        payload.dataset, payload.columns, payload.filters
    )
    report = SavedReport(
        organization_id=user.organization_id,
        name=payload.name,
        dataset=dataset,
        columns=columns,
        filters=filters,
        format=payload.format,
        created_by_id=user.id,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return SavedReportResponse.model_validate(report, from_attributes=True)


@router.put("/{report_id}", response_model=SavedReportResponse)
async def update_saved_report(
    report_id: uuid.UUID,
    payload: SavedReportUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "editor")),
):
    report = await _get_owned_report(db, report_id, user)
    data = payload.model_dump(exclude_unset=True)

    if "format" in data:
        _validate_format_or_400(data["format"])

    # Re-validate the spec against whichever dataset will be in effect.
    if any(k in data for k in ("dataset", "columns", "filters")):
        dataset = data.get("dataset", report.dataset)
        columns = data.get("columns", report.columns)
        filters = data.get("filters", report.filters)
        dataset, columns, filters = _validate_spec_or_400(dataset, columns, filters)
        data["dataset"], data["columns"], data["filters"] = dataset, columns, filters

    for field, value in data.items():
        setattr(report, field, value)
    await db.commit()
    await db.refresh(report)
    return SavedReportResponse.model_validate(report, from_attributes=True)


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "editor")),
):
    report = await _get_owned_report(db, report_id, user)
    await db.delete(report)
    await db.commit()


# ── Report schedules (nested under a saved report) ─────────────────────────────

@router.get("/{report_id}/schedules", response_model=list[ReportScheduleResponse])
async def list_schedules(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_owned_report(db, report_id, user)
    result = await db.execute(
        select(ReportSchedule)
        .where(ReportSchedule.saved_report_id == report_id)
        .order_by(ReportSchedule.created_at)
    )
    return [
        ReportScheduleResponse.model_validate(s, from_attributes=True)
        for s in result.scalars().all()
    ]


@router.post(
    "/{report_id}/schedules",
    response_model=ReportScheduleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_schedule(
    report_id: uuid.UUID,
    payload: ReportScheduleCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "editor")),
):
    await _get_owned_report(db, report_id, user)
    _validate_frequency_or_400(payload.frequency)
    if not payload.recipients:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one recipient is required",
        )
    schedule = ReportSchedule(
        organization_id=user.organization_id,
        saved_report_id=report_id,
        frequency=payload.frequency,
        day_of_week=payload.day_of_week,
        day_of_month=payload.day_of_month,
        recipients=payload.recipients,
        is_active=payload.is_active,
        next_run_at=compute_next_run(
            payload.frequency, payload.day_of_week, payload.day_of_month
        ),
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return ReportScheduleResponse.model_validate(schedule, from_attributes=True)


@router.put(
    "/{report_id}/schedules/{schedule_id}", response_model=ReportScheduleResponse
)
async def update_schedule(
    report_id: uuid.UUID,
    schedule_id: uuid.UUID,
    payload: ReportScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "editor")),
):
    await _get_owned_report(db, report_id, user)
    result = await db.execute(
        select(ReportSchedule).where(
            ReportSchedule.id == schedule_id,
            ReportSchedule.saved_report_id == report_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")

    data = payload.model_dump(exclude_unset=True)
    if "frequency" in data:
        _validate_frequency_or_400(data["frequency"])
    if "recipients" in data and not data["recipients"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one recipient is required",
        )

    for field, value in data.items():
        setattr(schedule, field, value)

    if any(k in data for k in ("frequency", "day_of_week", "day_of_month")):
        schedule.next_run_at = compute_next_run(
            schedule.frequency, schedule.day_of_week, schedule.day_of_month
        )

    await db.commit()
    await db.refresh(schedule)
    return ReportScheduleResponse.model_validate(schedule, from_attributes=True)


@router.delete(
    "/{report_id}/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_schedule(
    report_id: uuid.UUID,
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "editor")),
):
    await _get_owned_report(db, report_id, user)
    result = await db.execute(
        select(ReportSchedule).where(
            ReportSchedule.id == schedule_id,
            ReportSchedule.saved_report_id == report_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    await db.delete(schedule)
    await db.commit()
