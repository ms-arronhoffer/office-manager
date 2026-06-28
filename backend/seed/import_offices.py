from seed.helpers import get_workbook, safe_str, safe_int
from app.models import Manager, Office


def import_offices(session, organization_id=None):
    wb = get_workbook("Copy of Office Location Master List.xlsx")
    if not wb:
        return {}, {}

    manager_map = {}
    office_map = {}

    # First pass: collect all unique manager names from all sheets
    manager_names = set()
    for sheet_name in ["Active Locations by Office", "Inactive Locations"]:
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        start_row = 4 if "Active" in sheet_name else 2
        mgr_col = 4 if "Active" in sheet_name else 4  # 0-indexed: col E=4 for Active, col E=4 for Inactive

        for row in ws.iter_rows(min_row=start_row, values_only=True):
            mgr_name = safe_str(row[mgr_col] if len(row) > mgr_col else None)
            if mgr_name and mgr_name.lower() not in ("none", "n/a", ""):
                manager_names.add(mgr_name)

    # Also collect from HVAC and lease files later - for now just office managers
    print(f"  Found {len(manager_names)} unique managers")

    for name in sorted(manager_names):
        existing = session.query(Manager).filter_by(name=name).first()
        if existing:
            manager_map[name] = existing.id
        else:
            mgr = Manager(name=name, organization_id=organization_id)
            session.add(mgr)
            session.flush()
            manager_map[name] = mgr.id

    # Second pass: import active offices
    if "Active Locations by Office" in wb.sheetnames:
        ws = wb["Active Locations by Office"]
        count = 0
        for row in ws.iter_rows(min_row=4, values_only=True):
            office_num = safe_int(row[0])
            if office_num is None:
                continue
            location_name = safe_str(row[3])
            if not location_name:
                continue

            # Skip if already imported
            existing = session.query(Office).filter_by(office_number=office_num, is_active=True).first()
            if existing:
                office_map[office_num] = existing.id
                count += 1
                continue

            mgr_name = safe_str(row[4])
            mgr_id = manager_map.get(mgr_name)

            office = Office(
                office_number=office_num,
                region_number=safe_int(row[1]),
                location_type=safe_str(row[2]) or "Main",
                location_name=location_name,
                manager_id=mgr_id,
                is_active=True,
                organization_id=organization_id,
                mail_shipping=safe_str(row[5]),
                notes=safe_str(row[6]),
                address_line_1=safe_str(row[7]),
                address_line_2=safe_str(row[8]),
                city=safe_str(row[9]),
                state=safe_str(row[10]),
                zip_code=safe_str(str(row[11]).replace(".0", "")) if row[11] else None,
                phone_number=safe_str(row[12]),
                fax=safe_str(row[13]),
                email=safe_str(row[14]),
                other_names=safe_str(row[15]),
                sector=safe_str(row[16]),
                crown_property_on_site=safe_str(row[17]),
                additional_info=safe_str(row[18]) if len(row) > 18 else None,
            )
            session.add(office)
            session.flush()
            office_map[office_num] = office.id
            count += 1
        print(f"  Imported {count} active offices")

    # Import inactive offices
    if "Inactive Locations" in wb.sheetnames:
        ws = wb["Inactive Locations"]
        count = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            office_num = safe_int(row[0])
            if office_num is None:
                continue
            location_name = safe_str(row[3])
            if not location_name:
                continue

            # Skip if already imported
            existing = session.query(Office).filter_by(office_number=office_num, is_active=False).first()
            if existing:
                if office_num not in office_map:
                    office_map[office_num] = existing.id
                count += 1
                continue

            mgr_name = safe_str(row[4])
            mgr_id = manager_map.get(mgr_name)

            office = Office(
                office_number=office_num,
                region_number=safe_int(row[1]),
                location_type=safe_str(row[2]) or "",
                location_name=location_name,
                manager_id=mgr_id,
                is_active=False,
                organization_id=organization_id,
                address_line_1=safe_str(row[5]),
                address_line_2=safe_str(row[6]),
                city=safe_str(row[7]),
                state=safe_str(row[8]),
                zip_code=safe_str(str(row[9]).replace(".0", "")) if row[9] else None,
                phone_number=safe_str(row[10]),
                fax=safe_str(row[11]),
                email=safe_str(row[12]),
                other_names=safe_str(row[13]),
                sector=safe_str(row[14]),
                notes=safe_str(row[15]),
                additional_info=safe_str(row[16]) if len(row) > 16 else None,
                closing_notes=safe_str(row[17]) if len(row) > 17 else None,
            )
            session.add(office)
            session.flush()
            # Don't overwrite active offices in the map
            if office_num not in office_map:
                office_map[office_num] = office.id
            count += 1
        print(f"  Imported {count} inactive offices")

    session.flush()
    wb.close()
    return manager_map, office_map
