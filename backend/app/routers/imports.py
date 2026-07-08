"""Import router: template downloads and XLSX import uploads."""

from __future__ import annotations

import io
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from app.database import get_db
from app.auth.dependencies import require_role
from app.services.import_service import IMPORTERS

router = APIRouter()

# ── Template definitions ──────────────────────────────────────────────

TEMPLATES: dict[str, dict] = {
    "managers": {
        "filename": "managers_template.xlsx",
        "title": "Managers",
        "headers": ["Name", "Email", "Phone"],
        "example": ["John Smith", "jsmith@example.com", "555-0100"],
    },
    "offices": {
        "filename": "offices_template.xlsx",
        "title": "Offices",
        "headers": [
            "Office Number", "Region Number", "Location Type", "Location Name",
            "Manager", "Active", "Address Line 1", "Address Line 2", "City",
            "State", "Zip Code", "Phone", "Fax", "Email", "Mail/Shipping",
            "Sector", "Notes",
        ],
        "example": [
            101, 1, "office", "Main Office", "John Smith", "Yes",
            "123 Main St", "Suite 200", "Springfield", "IL", "62701",
            "555-0100", "555-0101", "main@example.com", "Same as office",
            "Government", "Example office",
        ],
    },
    "leases": {
        "filename": "leases_template.xlsx",
        "title": "Leases",
        "headers": [
            "Lease Name", "Office Number", "Manager", "Expiration Date",
            "Lessor Name", "Notice Period", "Notice Days", "Notice Date",
            "Notice Given Date", "Status", "Expiration Year",
        ],
        "example": [
            "101 - Main Office", 101, "John Smith", "12/31/2026",
            "ABC Properties", "90 Days", 90, "10/02/2026",
            "", "Active", 2026,
        ],
    },
    "landlords": {
        "filename": "landlords_template.xlsx",
        "title": "Landlords",
        "headers": [
            "ERN", "Office Name", "Office Number", "Landlord Company",
            "Contact Name", "Title", "Email", "Phone", "Mailing Address",
            "Online Sign In", "Vendor ID", "Notes",
        ],
        "example": [
            "ERN001", "Main Office", 101, "ABC Properties",
            "Jane Doe", "Property Manager", "jane@abc.com", "555-0200",
            "456 Oak Ave, Springfield IL", "portal.abc.com", "V-1234",
            "Primary landlord",
        ],
    },
    "vendors": {
        "filename": "vendors_template.xlsx",
        "title": "Vendors",
        "headers": [
            "Company Name", "Services", "Contact Name", "Email",
            "Phone", "Address", "Preferred", "Office Numbers", "Notes",
        ],
        "example": [
            "Acme Services", "HVAC Maintenance", "Bob Builder", "bob@acme.com",
            "555-0300", "789 Elm St", "Yes", "101;203;305",
            "Preferred HVAC vendor",
        ],
    },
    "transitions": {
        "filename": "transitions_template.xlsx",
        "title": "Transitions",
        "headers": [
            "Office Number", "Transition Type", "Address", "New Address",
            "Status", "Sheet Name", "Lease Expiration", "Estimated Date", "Notes",
        ],
        "example": [
            101, "relocation", "123 Main St", "456 New Blvd",
            "in_progress", "Sheet1", "12/31/2026", "06/01/2026",
            "Moving to larger space",
        ],
    },
    "hvac-contracts": {
        "filename": "hvac_contracts_template.xlsx",
        "title": "HVAC Contracts",
        "headers": [
            "Office Number", "Office Name", "HVAC Company", "Contact",
            "Comments", "Frequency", "Last Serviced", "Next Service",
            "Manager", "Landlord Handles",
        ],
        "example": [
            101, "Main Office", "Cool Air Inc", "Mike Tech",
            "Annual contract", "Quarterly", "01/15/2026", "04/15/2026",
            "John Smith", "No",
        ],
    },
}

VALID_ENTITIES = set(TEMPLATES.keys())


def _generate_template(entity: str) -> io.BytesIO:
    tmpl = TEMPLATES[entity]
    wb = Workbook()
    ws = wb.active
    ws.title = tmpl["title"][:31]

    bold = Font(bold=True)
    example_font = Font(italic=True, color="999999")
    example_fill = PatternFill(start_color="F5F5F5", end_color="F5F5F5", fill_type="solid")

    # Row 1: headers
    for col_idx, header in enumerate(tmpl["headers"], start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = bold

    # Row 2: example data
    for col_idx, val in enumerate(tmpl["example"], start=1):
        cell = ws.cell(row=2, column=col_idx, value=val)
        cell.font = example_font
        cell.fill = example_fill

    # Auto-size columns
    for col_idx, header in enumerate(tmpl["headers"], start=1):
        max_len = len(str(header))
        if col_idx - 1 < len(tmpl["example"]) and tmpl["example"][col_idx - 1] is not None:
            max_len = max(max_len, len(str(tmpl["example"][col_idx - 1])))
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 4, 50)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


@router.get("/{entity}/template")
async def download_template(
    entity: str,
    _=Depends(require_role("admin", "editor")),
):
    if entity not in VALID_ENTITIES:
        raise HTTPException(status_code=404, detail=f"Unknown entity: {entity}")
    tmpl = TEMPLATES[entity]
    buf = _generate_template(entity)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{tmpl["filename"]}"'},
    )


@router.post("/{entity}/import")
async def import_data(
    entity: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role("admin", "editor")),
):
    if entity not in VALID_ENTITIES:
        raise HTTPException(status_code=404, detail=f"Unknown entity: {entity}")

    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="File must be an XLSX file")

    contents = await file.read()
    importer = IMPORTERS[entity]

    try:
        result = await importer(db, contents)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Import failed: {str(e)}")

    return result.to_dict()
