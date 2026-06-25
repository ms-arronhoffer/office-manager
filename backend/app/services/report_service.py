from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from app.models import (
    Office, Manager, Lease, Landlord, HvacContract,
    HqPmTask, HqHeatPump, OfficeTransition,
    MaintenanceTicket, TicketCategory,
)
from app.models.user import User
from app.utils.pdf_generator import generate_pdf
from app.utils.csv_generator import generate_csv
from app.utils.xlsx_generator import generate_xlsx

DATASET_CONFIGS = {
    "offices": {
        "model": Office,
        "title": "Office Directory",
        "columns": {
            "office_number": "Office #",
            "location_name": "Location",
            "location_type": "Type",
            "city": "City",
            "state": "State",
            "zip_code": "Zip",
            "phone_number": "Phone",
            "email": "Email",
            "sector": "Sector",
            "is_active": "Active",
        },
        "filters_config": [
            {"key": "is_active", "label": "Active", "type": "boolean"},
            {"key": "location_type", "label": "Location Type", "type": "text"},
            {"key": "state", "label": "State", "type": "text"},
        ],
    },
    "leases": {
        "model": Lease,
        "title": "Lease Report",
        "columns": {
            "lease_name": "Lease Name",
            "lease_expiration": "Expiration",
            "lessor_name": "Lessor",
            "notice_period": "Notice Period",
            "lease_notice_date": "Notice Date",
            "notice_given_date": "Notice Given",
            "expiration_year": "Year",
        },
        "filters_config": [
            {"key": "expiration_year", "label": "Expiration Year", "type": "number"},
        ],
    },
    "landlords": {
        "model": Landlord,
        "title": "Landlord Contacts",
        "columns": {
            "office_name": "Office",
            "landlord_company": "Company",
            "contact_name": "Contact",
            "contact_email": "Email",
            "contact_phone": "Phone",
            "vendor_id": "Vendor ID",
        },
        "filters_config": [],
    },
    "hvac_contracts": {
        "model": HvacContract,
        "title": "HVAC Contracts",
        "columns": {
            "office_name": "Office",
            "hvac_company": "HVAC Company",
            "contact": "Contact",
            "frequency": "Frequency",
            "last_serviced": "Last Serviced",
            "next_service": "Next Service",
            "landlord_handles": "LL Handles",
        },
        "filters_config": [
            {"key": "landlord_handles", "label": "Landlord Handles", "type": "boolean"},
        ],
    },
    "transitions": {
        "model": OfficeTransition,
        "title": "Office Transitions",
        "columns": {
            "office_number": "Office #",
            "transition_type": "Type",
            "address": "Address",
            "status": "Status",
            "sheet_name": "Source",
        },
        "filters_config": [
            {"key": "status", "label": "Status", "type": "select", "options": [
                {"value": "planned", "label": "Planned"},
                {"value": "in_progress", "label": "In Progress"},
                {"value": "completed", "label": "Completed"},
                {"value": "cancelled", "label": "Cancelled"},
            ]},
            {"key": "transition_type", "label": "Type", "type": "text"},
        ],
    },
    "hq_pm_tasks": {
        "model": HqPmTask,
        "title": "HQ PM Schedule",
        "columns": {
            "equipment_category": "Category",
            "task_description": "Task",
            "frequency": "Frequency",
            "can_in_house": "In-House",
            "next_due_date": "Due Date",
            "status": "Status",
            "notes": "Notes",
        },
        "filters_config": [
            {"key": "status", "label": "Status", "type": "text"},
            {"key": "equipment_category", "label": "Category", "type": "text"},
        ],
    },
    "hq_heat_pumps": {
        "model": HqHeatPump,
        "title": "HQ Heat Pumps",
        "columns": {
            "unit_id": "Unit ID",
            "location_desc": "Location",
            "make": "Make",
            "model": "Model",
            "serial_number": "Serial #",
            "install_year": "Year",
        },
        "filters_config": [],
    },
    "maintenance_tickets": {
        "model": MaintenanceTicket,
        "title": "Maintenance Tickets",
        "columns": {
            "subject": "Subject",
            "priority": "Priority",
            "status": "Status",
            "category_name": "Category",
            "office_name": "Office",
            "created_by_name": "Created By",
            "assigned_to_name": "Assigned To",
            "location_hours": "Location Hours",
            "description": "Description",
            "created_at": "Created At",
        },
        "filters_config": [
            {"key": "priority", "label": "Priority", "type": "select", "options": [
                {"value": "low", "label": "Low"},
                {"value": "medium", "label": "Medium"},
                {"value": "high", "label": "High"},
            ]},
            {"key": "status", "label": "Status", "type": "select", "options": [
                {"value": "open", "label": "Open"},
                {"value": "in_progress", "label": "In Progress"},
                {"value": "closed", "label": "Closed"},
            ]},
        ],
        "eager_loads": lambda: [
            joinedload(MaintenanceTicket.category),
            joinedload(MaintenanceTicket.office),
            joinedload(MaintenanceTicket.created_by),
            joinedload(MaintenanceTicket.assigned_to),
        ],
        "virtual_columns": {
            "category_name": lambda r: r.category.name if r.category else "",
            "office_name": lambda r: r.office.location_name if r.office else "",
            "created_by_name": lambda r: r.created_by.display_name if r.created_by else "",
            "assigned_to_name": lambda r: r.assigned_to.name if r.assigned_to else "",
        },
    },
}

# Columns that exist on the model and can be used for WHERE filters
_FILTERABLE_ATTRS = {
    "maintenance_tickets": {"priority", "status"},
}


class ReportService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def get_templates(self) -> list[dict]:
        return [
            {
                "id": key,
                "title": cfg["title"],
                "columns": [{"key": k, "label": v} for k, v in cfg["columns"].items()],
                "filters_config": cfg.get("filters_config", []),
            }
            for key, cfg in DATASET_CONFIGS.items()
        ]

    async def fetch_data(self, dataset: str, columns: list[str] | None = None, filters: dict | None = None):
        """Fetch data from database, returning (title, headers, rows) or None."""
        config = DATASET_CONFIGS.get(dataset)
        if not config:
            return None

        model = config["model"]
        query = select(model)

        # Apply eager loads if defined (for relationship-based columns)
        eager_loads = config.get("eager_loads")
        if eager_loads:
            for opt in eager_loads():
                query = query.options(opt)

        # Apply soft-delete filter if model has is_deleted
        if hasattr(model, "is_deleted"):
            query = query.where(model.is_deleted == False)  # noqa: E712

        # Apply filters (only on real model attributes)
        if filters:
            filterable = _FILTERABLE_ATTRS.get(dataset, set(config["columns"].keys()))
            for key, value in filters.items():
                if value is None or value == "":
                    continue
                if key not in filterable and not hasattr(model, key):
                    continue
                if hasattr(model, key):
                    # Handle boolean string conversion
                    col = getattr(model, key)
                    if str(value).lower() in ("true", "false"):
                        value = str(value).lower() == "true"
                    query = query.where(col == value)

        result = await self.db.execute(query)
        records = result.unique().scalars().all()

        if columns:
            selected_cols = {k: v for k, v in config["columns"].items() if k in columns}
        else:
            selected_cols = config["columns"]

        headers = list(selected_cols.values())
        virtual = config.get("virtual_columns", {})
        rows = []
        for record in records:
            row = []
            for col_key in selected_cols.keys():
                if col_key in virtual:
                    val = virtual[col_key](record)
                else:
                    val = getattr(record, col_key, None)
                # Stringify for display
                if val is None:
                    val = ""
                elif isinstance(val, bool):
                    val = "Yes" if val else "No"
                else:
                    val = str(val)
                row.append(val)
            rows.append(row)

        return config["title"], headers, rows

    async def preview(self, dataset: str, columns: list[str] | None = None, filters: dict | None = None, limit: int = 500):
        result = await self.fetch_data(dataset, columns, filters)
        if result is None:
            return None
        title, headers, rows = result
        return {
            "title": title,
            "headers": headers,
            "rows": rows[:limit],
            "total": len(rows),
        }

    async def generate(self, dataset: str, format: str, columns: list[str] | None = None, filters: dict | None = None):
        result = await self.fetch_data(dataset, columns, filters)
        if result is None:
            return None, None

        title, headers, rows = result

        if format == "pdf":
            buffer = generate_pdf(title, headers, rows)
            return buffer, "application/pdf"
        elif format == "xlsx":
            buffer = generate_xlsx(title, headers, rows)
            return buffer, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            buffer = generate_csv(headers, rows)
            return buffer, "text/csv"
