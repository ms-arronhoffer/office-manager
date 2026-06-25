from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wizard_config import WizardConfig

DEFAULT_STEPS = [
    # ── Welcome ──
    {
        "id": "start",
        "type": "message",
        "text": "Welcome to the SwiftLease Portal! I can help you with several tasks.",
        "next": "action_select",
    },
    # ── Action Selection (decision entry point) ──
    {
        "id": "action_select",
        "type": "choice",
        "text": "What would you like to do?",
        "field": "_action",
        "options": [
            {"label": "Create a Maintenance Ticket", "value": "ticket", "next": "ticket_office"},
            {"label": "Look Up Vendors for an Office", "value": "vendors", "next": "vendor_office"},
            {"label": "View HVAC Contracts for an Office", "value": "hvac", "next": "hvac_office"},
        ],
    },

    # ── Ticket Flow ──
    {
        "id": "ticket_office",
        "type": "select",
        "text": "Which office is this maintenance request for?",
        "field": "office_id",
        "options": "__offices__",
        "next": "ticket_category",
    },
    {
        "id": "ticket_category",
        "type": "choice",
        "text": "What type of issue are you experiencing?",
        "field": "category_id",
        "options": "__categories__",
        "next": "ticket_subject",
    },
    {
        "id": "ticket_subject",
        "type": "text",
        "text": "Please provide a brief summary of the issue (this will be the ticket subject):",
        "field": "subject",
        "next": "ticket_description",
    },
    {
        "id": "ticket_description",
        "type": "text",
        "text": "Now describe the issue in more detail:",
        "field": "description",
        "next": "ticket_location_hours",
    },
    {
        "id": "ticket_location_hours",
        "type": "text",
        "text": "What are the location hours or best times for maintenance access? (optional \u2014 type 'skip' to skip)",
        "field": "location_hours",
        "optional": True,
        "next": "ticket_priority",
    },
    {
        "id": "ticket_priority",
        "type": "select",
        "text": "How urgent is this?",
        "field": "priority",
        "options": [
            {"label": "Low \u2014 can wait", "value": "low"},
            {"label": "Medium \u2014 needs attention soon", "value": "medium"},
            {"label": "High \u2014 urgent, impacting work", "value": "high"},
        ],
        "next": "ticket_confirm",
    },
    {
        "id": "ticket_confirm",
        "type": "confirm",
        "text": "Here's a summary of your request. Ready to submit?",
    },

    # ── Vendor Lookup Flow ──
    {
        "id": "vendor_office",
        "type": "select",
        "text": "Which office would you like to look up vendors for?",
        "field": "office_id",
        "options": "__offices__",
        "next": "vendor_results",
    },
    {
        "id": "vendor_results",
        "type": "display_results",
        "text": "Here are the vendors assigned to this office:",
        "endpoint": "/offices/{office_id}/vendors",
        "params_from": ["office_id"],
        "columns": [
            {"key": "company_name", "header": "Company"},
            {"key": "services", "header": "Services"},
            {"key": "contact_name", "header": "Contact"},
            {"key": "contact_email", "header": "Email"},
            {"key": "contact_phone", "header": "Phone"},
            {"key": "is_preferred", "header": "Preferred"},
        ],
    },

    # ── HVAC Contract Flow ──
    {
        "id": "hvac_office",
        "type": "select",
        "text": "Which office would you like to view HVAC contracts for?",
        "field": "office_id",
        "options": "__offices__",
        "next": "hvac_results",
    },
    {
        "id": "hvac_results",
        "type": "display_results",
        "text": "Here are the HVAC contracts for this office:",
        "endpoint": "/offices/{office_id}/hvac-contracts",
        "params_from": ["office_id"],
        "columns": [
            {"key": "hvac_company", "header": "HVAC Company"},
            {"key": "contact", "header": "Contact"},
            {"key": "frequency", "header": "Frequency"},
            {"key": "last_serviced", "header": "Last Serviced"},
            {"key": "next_service", "header": "Next Service"},
            {"key": "landlord_handles", "header": "Landlord Handles"},
        ],
    },
]


async def seed_default_wizard_config(db: AsyncSession) -> None:
    """Insert a default wizard config if none exists."""
    result = await db.execute(select(WizardConfig).limit(1))
    if result.scalar_one_or_none() is not None:
        return

    config = WizardConfig(
        name="Decision Portal",
        description="Multi-action portal: create tickets, look up vendors, view HVAC contracts.",
        steps=DEFAULT_STEPS,
        is_active=True,
        is_default=True,
    )
    db.add(config)
    await db.commit()
