import re
from seed.helpers import get_workbook, safe_str, safe_int, safe_date
from app.models import HvacContract, HvacOfficeDetail


def import_hvac_contracts(session, manager_map, office_map):
    # Skip if already imported
    existing = session.query(HvacContract).count()
    if existing > 0:
        print(f"  HVAC contracts already exist ({existing}), skipping")
        return

    wb = get_workbook("HVAC CONTRACT TRACKER.xlsx")
    if not wb:
        return

    # Main tracker sheet
    if "HVAC CONTRACT TRACKER" in wb.sheetnames:
        ws = wb["HVAC CONTRACT TRACKER"]
        count = 0
        for row in ws.iter_rows(min_row=3, values_only=True):
            office_num = safe_int(row[0])
            office_name = safe_str(row[1])
            if not office_name:
                continue

            # Manager is in last column (col 8, index 8)
            mgr_name = safe_str(row[8]) if len(row) > 8 else None
            mgr_id = manager_map.get(mgr_name)

            contract = HvacContract(
                office_id=office_map.get(office_num) if office_num else None,
                office_number=office_num,
                office_name=office_name,
                hvac_company=safe_str(row[2]),
                contact=safe_str(row[3]),
                comments=safe_str(row[4]),
                frequency=safe_str(row[5]),
                last_serviced=safe_str(row[6]),
                last_serviced_date=safe_date(row[6]),
                next_service=safe_str(row[7]),
                next_service_date=safe_date(row[7]),
                manager_id=mgr_id,
                landlord_handles=False,
            )
            session.add(contract)
            count += 1
        print(f"  Imported {count} HVAC contracts from main tracker")

    # LL Handles sheet - only first group of 8 columns
    if "LL Handles HVAC Maint" in wb.sheetnames:
        ws = wb["LL Handles HVAC Maint"]
        count = 0
        for row in ws.iter_rows(min_row=3, values_only=True):
            office_name = safe_str(row[0])
            if not office_name:
                continue

            mgr_name = safe_str(row[7]) if len(row) > 7 else None
            mgr_id = manager_map.get(mgr_name)

            contract = HvacContract(
                office_name=office_name,
                hvac_company=safe_str(row[1]),
                contact=safe_str(row[2]),
                comments=safe_str(row[3]),
                frequency=safe_str(row[4]),
                last_serviced=safe_str(row[5]),
                last_serviced_date=safe_date(row[5]),
                next_service=safe_str(row[6]),
                next_service_date=safe_date(row[6]),
                manager_id=mgr_id,
                landlord_handles=True,
            )
            session.add(contract)
            count += 1
        print(f"  Imported {count} LL-handled HVAC contracts")

    # Individual office detail sheets
    skip_sheets = {"HVAC CONTRACT TRACKER", "LL Handles HVAC Maint"}
    detail_count = 0
    for sheet_name in wb.sheetnames:
        if sheet_name in skip_sheets:
            continue

        ws = wb[sheet_name]
        # Collect all text from columns A-D
        contractor_lines = []
        responsibility_lines = []
        lease_text = None

        for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 20), values_only=True):
            a_val = safe_str(row[0])
            b_val = safe_str(row[1]) if len(row) > 1 else None
            c_val = safe_str(row[2]) if len(row) > 2 else None
            d_val = safe_str(row[3]) if len(row) > 3 else None

            if a_val:
                contractor_lines.append(a_val)
            if b_val:
                contractor_lines.append(f"[{b_val}]")
            if c_val:
                responsibility_lines.append(c_val)
            if d_val:
                lease_date = safe_date(d_val)
                if lease_date:
                    lease_text = str(d_val)

        # Extract frequency from column B row 1-2
        freq = None
        for row in ws.iter_rows(min_row=1, max_row=2, values_only=True):
            if len(row) > 1:
                f = safe_str(row[1])
                if f and any(kw in f.lower() for kw in ["quarter", "semi", "annual"]):
                    freq = f
                    break

        detail = HvacOfficeDetail(
            sheet_name=sheet_name,
            hvac_contractor="\n".join(contractor_lines[:5]) if contractor_lines else None,
            frequency=freq,
            responsibility_summary=responsibility_lines[0] if responsibility_lines else None,
            responsibility_detail="\n".join(responsibility_lines) if responsibility_lines else None,
            lease_expiration_text=lease_text,
            lease_expiration=safe_date(lease_text) if lease_text else None,
        )
        session.add(detail)
        detail_count += 1

    print(f"  Imported {detail_count} HVAC office detail sheets")
    session.commit()
    wb.close()
