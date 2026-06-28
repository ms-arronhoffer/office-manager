"""Seed a realistic set of service vendors.

There is no vendor spreadsheet in ``seed/data`` (vendors are managed inside the
app rather than tracked in the source workbooks), so this importer generates a
deterministic, realistic vendor roster covering the service categories used by
maintenance tickets.  Each vendor is linked to a handful of existing offices so
the vendor-to-office relationship is populated out of the box.
"""

from app.models import Vendor, Office


# (company_name, services, contact_name, contact_email, contact_phone,
#  address_line_1, city, state, zip_code, is_preferred, notes)
_VENDORS = [
    ("BrightSpark Electrical", "Electrical", "Marcus Reilly",
     "dispatch@brightsparkelectric.com", "(312) 555-0142",
     "1820 W Industrial Ave", "Chicago", "IL", "60622", True,
     "Licensed master electricians; 24/7 emergency line."),
    ("Cardinal Plumbing & Drain", "Plumbing", "Denise Okafor",
     "service@cardinalplumbing.com", "(214) 555-0198",
     "905 Commerce St", "Dallas", "TX", "75202", True,
     "Drain cleaning, water heaters, backflow testing."),
    ("Summit Mechanical HVAC", "HVAC", "Trevor Lindqvist",
     "schedule@summitmechanical.com", "(303) 555-0177",
     "4400 Brighton Blvd", "Denver", "CO", "80216", True,
     "Preferred HVAC partner; quarterly PM agreements available."),
    ("Polished Pro Cleaning", "Cleaning", "Aisha Bennett",
     "office@polishedpro.com", "(404) 555-0110",
     "212 Peachtree Center", "Atlanta", "GA", "30303", False,
     "Nightly janitorial and periodic deep cleans."),
    ("SecureShred Document Services", "Shredding", "Paul Mendez",
     "pickup@secureshred.com", "(602) 555-0163",
     "3300 N 7th St", "Phoenix", "AZ", "85014", False,
     "NAID AAA certified on-site and off-site shredding."),
    ("GuardLine Pest Control", "Pest Control", "Hannah Whitfield",
     "service@guardlinepest.com", "(615) 555-0124",
     "1717 Church St", "Nashville", "TN", "37203", False,
     "Monthly integrated pest management plans."),
    ("Vertical Elevator Service", "Elevator", "Sergei Antonov",
     "support@verticalelevator.com", "(216) 555-0188",
     "640 Superior Ave E", "Cleveland", "OH", "44114", True,
     "Elevator inspection, repair, and modernization."),
    ("FireGuard Safety Systems", "Fire/Safety", "Olivia Tran",
     "compliance@fireguardsystems.com", "(206) 555-0151",
     "1200 Westlake Ave N", "Seattle", "WA", "98109", True,
     "Sprinkler, alarm, and extinguisher inspections."),
    ("AllTrade Facility Repair", "General Repair", "Devon Carter",
     "work@alltradefacility.com", "(617) 555-0139",
     "75 State St", "Boston", "MA", "02109", False,
     "General handyman, drywall, doors, and locks."),
    ("Clearview Window & Glass", "General Repair", "Renata Silva",
     "quotes@clearviewglass.com", "(305) 555-0172",
     "800 Brickell Ave", "Miami", "FL", "33131", False,
     "Storefront glass, window repair, and replacement."),
]


def import_vendors(session, office_map, organization_id=None):
    """Create the seed vendor roster and link each vendor to some offices."""
    # Skip if already imported
    existing = session.query(Vendor).count()
    if existing > 0:
        print(f"  Vendors already exist ({existing}), skipping")
        return {}

    # Stable, ordered list of office ids so the office assignment is
    # deterministic regardless of dict ordering.
    office_ids = [office_map[num] for num in sorted(office_map)]
    office_by_id = {o.id: o for o in session.query(Office).all()}

    vendor_map = {}  # company_name -> vendor.id
    count = 0
    for idx, (
        company_name, services, contact_name, contact_email, contact_phone,
        address_line_1, city, state, zip_code, is_preferred, notes,
    ) in enumerate(_VENDORS):
        vendor = Vendor(
            organization_id=organization_id,
            company_name=company_name,
            services=services,
            contact_name=contact_name,
            contact_email=contact_email,
            contact_phone=contact_phone,
            address_line_1=address_line_1,
            city=city,
            state=state,
            zip_code=zip_code,
            is_preferred=is_preferred,
            notes=notes,
        )

        # Link each vendor to a small, deterministic slice of offices so the
        # vendor-office relationship is populated. Offices are striped across
        # vendors to give reasonable coverage.
        if office_ids:
            linked = office_ids[idx::len(_VENDORS)][:5]
            vendor.offices = [office_by_id[oid] for oid in linked if oid in office_by_id]

        session.add(vendor)
        session.flush()
        vendor_map[company_name] = vendor.id
        count += 1

    print(f"  Imported {count} vendors")
    return vendor_map
