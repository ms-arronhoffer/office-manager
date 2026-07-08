from seed.helpers import (
    get_workbook, safe_str, safe_date, parse_notice_days, parse_office_number_from_name
)
from app.models import Lease, LeaseNote, Manager
from app.schemas.lease import normalize_lease_status
from sqlalchemy import select


def import_leases(session, manager_map, office_map, organization_id=None):
    # Skip if already imported
    existing = session.query(Lease).count()
    if existing > 0:
        print(f"  Leases already exist ({existing}), skipping")
        return

    wb = get_workbook("Copy of Lease Expiration Notice Dates.xlsx")
    if not wb:
        return

    year_sheets = ["2023", "2024", "2025", "2026", "2027", "2028", "2029", "2030", "2031"]
    total = 0

    for sheet_name in year_sheets:
        if sheet_name not in wb.sheetnames:
            continue

        ws = wb[sheet_name]
        year = int(sheet_name)

        # 2023 has no Lessor Name column (7 base cols), others have 8
        has_lessor = (year != 2023)
        base_cols = 8 if has_lessor else 7

        count = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            lease_name = safe_str(row[0])
            if not lease_name:
                continue

            manager_name = safe_str(row[1])
            mgr_id = manager_map.get(manager_name)

            # If manager not in map, try to create
            if manager_name and not mgr_id and manager_name.lower() not in ("none", "n/a", "hq"):
                existing = session.execute(
                    select(Manager).where(Manager.name == manager_name)
                ).scalar_one_or_none()
                if existing:
                    mgr_id = existing.id
                    manager_map[manager_name] = mgr_id
                else:
                    mgr = Manager(name=manager_name, organization_id=organization_id)
                    session.add(mgr)
                    session.flush()
                    mgr_id = mgr.id
                    manager_map[manager_name] = mgr_id

            office_num = parse_office_number_from_name(lease_name)
            office_id = office_map.get(office_num) if office_num else None

            if has_lessor:
                lease_exp = safe_date(row[2])
                lessor = safe_str(row[3])
                notice_period = safe_str(row[4])
                notice_date = safe_date(row[5])
                notice_given = safe_date(row[6])
                quarem_val = row[7] if len(row) > 7 else None
            else:
                lease_exp = safe_date(row[2])
                lessor = None
                notice_period = safe_str(row[3])
                notice_date = safe_date(row[4])
                notice_given = safe_date(row[5])
                quarem_val = row[6] if len(row) > 6 else None

            lease_status = normalize_lease_status(quarem_val)

            lease = Lease(
                office_id=office_id,
                lease_name=lease_name,
                manager_id=mgr_id,
                organization_id=organization_id,
                lease_expiration=lease_exp,
                lessor_name=lessor,
                notice_period=notice_period,
                notice_period_days=parse_notice_days(notice_period),
                lease_notice_date=notice_date,
                notice_given_date=notice_given,
                status=lease_status,
                expiration_year=year,
            )
            session.add(lease)
            session.flush()

            # Import notes from remaining columns
            note_order = 0
            for i in range(base_cols, len(row)):
                note_text = safe_str(row[i])
                if note_text:
                    note = LeaseNote(
                        lease_id=lease.id,
                        note_text=note_text,
                        note_order=note_order,
                    )
                    session.add(note)
                    note_order += 1

            count += 1

        print(f"  Year {year}: {count} leases")
        total += count

    wb.close()
    print(f"  Total leases imported: {total}")
