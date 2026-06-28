"""Seed a realistic set of maintenance tickets.

Maintenance tickets are created inside the app rather than tracked in the source
workbooks, so this importer generates a deterministic, realistic set of tickets
spread across the seeded offices, ticket categories, vendors, and managers.  The
generated tickets cover the full lifecycle (open / in_progress / closed) and a
range of priorities so dashboards, SLA views, and the work-order UI have data to
display out of the box.
"""

from datetime import datetime, timedelta, timezone

from app.models import (
    MaintenanceTicket,
    TicketCategory,
    TicketNote,
    Vendor,
    User,
)
from app.models.office import Office, Manager


# Per-category ticket templates: (subject, description, priority, default
# vendor service to match). One representative ticket type per category keeps
# the generated data realistic and easy to reason about.
_TEMPLATES = [
    ("Electrical", "Flickering lights in conference room",
     "Overhead lighting in the main conference room flickers intermittently. "
     "Suspect a failing ballast or loose wiring.", "high"),
    ("Plumbing", "Leaking faucet in break room",
     "The break room sink faucet drips continuously and the cabinet below is "
     "showing water damage.", "medium"),
    ("HVAC", "AC not cooling on south side",
     "Offices on the south side of the floor are not cooling below 78F. "
     "Thermostat reads correctly but no cold air from the vents.", "high"),
    ("Cleaning", "Carpet stain in reception area",
     "Large coffee stain in the reception waiting area carpet needs a deep "
     "clean before the client visit next week.", "low"),
    ("Shredding", "Schedule confidential document shredding",
     "Two full bins of confidential client documents are ready for certified "
     "on-site shredding.", "low"),
    ("Pest Control", "Ants reported in kitchen area",
     "Staff have reported ants near the kitchen counters and trash area. "
     "Request inspection and treatment.", "medium"),
    ("Elevator", "Elevator making grinding noise",
     "The main elevator makes a grinding noise between floors 2 and 3. "
     "Please inspect for safety before continued use.", "high"),
    ("Fire/Safety", "Annual fire extinguisher inspection",
     "All fire extinguishers on the floor are due for their annual inspection "
     "and tag update.", "medium"),
    ("General Repair", "Broken door handle on main entrance",
     "The handle on the main suite entrance door is loose and the latch no "
     "longer catches properly.", "medium"),
]

# Cycle of lifecycle states so the seeded tickets span the full workflow.
_STATUS_CYCLE = ["open", "in_progress", "closed", "open", "closed", "in_progress"]


def _match_vendor(service, vendors):
    """Return a vendor id whose services match the category, if any."""
    if not service:
        return None
    for v in vendors:
        if v.services and service.lower() in v.services.lower():
            return v.id
    return None


def import_maintenance_tickets(session, office_map, organization_id=None):
    """Create seed maintenance tickets across offices and categories."""
    # Skip if already imported
    existing = session.query(MaintenanceTicket).count()
    if existing > 0:
        print(f"  Maintenance tickets already exist ({existing}), skipping")
        return

    categories = {c.name: c for c in session.query(TicketCategory).all()}
    if not categories:
        print("  [SKIP] No ticket categories found; cannot seed tickets")
        return

    # Need a creating user (the seeded admin) for created_by_id.
    creator = (
        session.query(User)
        .filter(User.organization_id == organization_id)
        .order_by(User.created_at.asc())
        .first()
    )
    if creator is None:
        creator = session.query(User).order_by(User.created_at.asc()).first()
    if creator is None:
        print("  [SKIP] No user found; cannot seed tickets (created_by required)")
        return

    vendors = session.query(Vendor).all()
    managers = session.query(Manager).order_by(Manager.name.asc()).all()

    # Stable, ordered office ids.
    office_ids = [office_map[num] for num in sorted(office_map)]
    offices_by_id = {o.id: o for o in session.query(Office).all()}
    if not office_ids:
        print("  [SKIP] No offices found; cannot seed tickets")
        return

    now = datetime.now(timezone.utc)
    count = 0

    # Generate one ticket per office, cycling through the category templates so
    # categories, priorities, and statuses are evenly represented.
    for idx, office_id in enumerate(office_ids):
        office = offices_by_id.get(office_id)
        cat_name, subject, description, priority = _TEMPLATES[idx % len(_TEMPLATES)]
        category = categories.get(cat_name)
        if category is None:
            # Category list differs from templates; fall back to any category.
            category = next(iter(categories.values()))

        status = _STATUS_CYCLE[idx % len(_STATUS_CYCLE)]
        vendor_id = _match_vendor(cat_name, vendors)
        assigned_to_id = managers[idx % len(managers)].id if managers else None

        created_at = now - timedelta(days=(idx % 45) + 1)
        scheduled_date = created_at + timedelta(days=2)

        ticket = MaintenanceTicket(
            organization_id=organization_id,
            subject=subject,
            description=description,
            priority=priority,
            status=status,
            category_id=category.id,
            office_id=office_id,
            location_hours="Mon-Fri 8:00 AM - 5:00 PM",
            created_by_id=creator.id,
            assigned_to_id=assigned_to_id,
            vendor_id=vendor_id,
            scheduled_date=scheduled_date,
            estimated_duration_minutes=120,
        )

        if status == "in_progress":
            ticket.actual_start_at = created_at + timedelta(days=1)
            ticket.technician_name = "Field Technician"
        elif status == "closed":
            ticket.actual_start_at = created_at + timedelta(days=1)
            ticket.actual_end_at = created_at + timedelta(days=1, hours=3)
            ticket.closed_at = created_at + timedelta(days=1, hours=3)
            ticket.technician_name = "Field Technician"
            if vendor_id:
                ticket.vendor_completed_at = ticket.closed_at
                ticket.vendor_completion_notes = "Work completed and verified on site."

        session.add(ticket)
        session.flush()

        # Add an intake note for a bit of activity history.
        loc = office.location_name if office else "the location"
        session.add(
            TicketNote(
                ticket_id=ticket.id,
                note_text=f"Ticket created for {loc}. Awaiting scheduling.",
                note_order=0,
                created_by_id=creator.id,
            )
        )
        count += 1

    print(f"  Imported {count} maintenance tickets")
