from seed.helpers import get_workbook, safe_str
from app.models import Landlord, LandlordAdditionalName, Office


def import_landlords(session, office_map):
    """Import landlords and additional landlord names.

    Links landlords to offices by matching office_name (col 1) against
    Office.location_name (case-insensitive).  Falls back to ern-as-number
    if a name match is not found.
    """
    # Skip if already imported
    existing = session.query(Landlord).count()
    if existing > 0:
        print(f"  Landlords already exist ({existing}), skipping")
        return

    wb = get_workbook("Copy of Landlord Contacts.xlsx")
    if not wb:
        return

    # Build a location_name → office_id lookup from already-imported offices
    offices = session.query(Office).all()
    office_name_to_id = {
        o.location_name.strip().lower(): o.id
        for o in offices
        if o.location_name
    }

    landlord_vendor_map = {}  # vendor_id → landlord.id

    # ------------------------------------------------------------------
    # Sheet1: main landlord contacts
    # Row 1 header: ern, Office, Address, Landlord Company, Contact Name,
    #               Title, Contact Email, Contact Phone,
    #               Contact Mailing Address, Online Sign In, Vendor ID
    # Data from row 2.
    # ------------------------------------------------------------------
    if "Sheet1" in wb.sheetnames:
        ws = wb["Sheet1"]
        count = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            if all(v is None for v in row[:5]):
                continue

            ern = safe_str(row[0])
            office_name = safe_str(row[1])
            address = safe_str(row[2])
            landlord_company = safe_str(row[3])
            contact_name = safe_str(row[4])
            title = safe_str(row[5]) if len(row) > 5 else None
            contact_email = safe_str(row[6]) if len(row) > 6 else None
            contact_phone = safe_str(row[7]) if len(row) > 7 else None
            contact_mailing_address = safe_str(row[8]) if len(row) > 8 else None
            online_sign_in = safe_str(row[9]) if len(row) > 9 else None
            vendor_id = safe_str(row[10]) if len(row) > 10 else None

            # Normalise ern (openpyxl can return numeric cells as "12345.0")
            if ern and ern.endswith(".0"):
                ern = ern[:-2]

            # Resolve office_id: prefer location_name match
            office_id = None
            if office_name:
                office_id = office_name_to_id.get(office_name.strip().lower())
            # Fallback: treat ern as office number
            if office_id is None and ern:
                try:
                    office_id = office_map.get(int(float(ern)))
                except (ValueError, TypeError):
                    pass

            landlord = Landlord(
                ern=ern,
                office_name=office_name,
                office_id=office_id,
                address=address,
                landlord_company=landlord_company,
                contact_name=contact_name,
                title=title,
                contact_email=contact_email,
                contact_phone=contact_phone,
                contact_mailing_address=contact_mailing_address,
                online_sign_in=online_sign_in,
                vendor_id=vendor_id,
            )
            session.add(landlord)
            session.flush()

            if vendor_id:
                landlord_vendor_map[vendor_id] = landlord.id

            count += 1
        print(f"  Imported {count} landlord contacts")

    # ------------------------------------------------------------------
    # Additional LandlordCO Names sheet
    # Row 1 header: VENDOR ID, C/O NAME, VENDOR NAME, OTHER NAMES, Additional Names
    # Data from row 2.
    # ------------------------------------------------------------------
    if "Additional LandlordCO Names" in wb.sheetnames:
        ws = wb["Additional LandlordCO Names"]
        count = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            vendor_id = safe_str(row[0])
            if not vendor_id:
                continue

            landlord_id = landlord_vendor_map.get(vendor_id)

            additional = LandlordAdditionalName(
                landlord_id=landlord_id,
                vendor_id=vendor_id,
                co_name=safe_str(row[1]),
                vendor_name=safe_str(row[2]),
                other_names=safe_str(row[3]) if len(row) > 3 else None,
                additional_names=safe_str(row[4]) if len(row) > 4 else None,
            )
            session.add(additional)
            count += 1

        session.flush()
        print(f"  Imported {count} additional landlord names")

    wb.close()
