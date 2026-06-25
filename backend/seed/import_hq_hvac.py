from seed.helpers import get_workbook, safe_str, safe_date
from app.models.hq_hvac import (
    HqHeatPump, HqHvacIssue, HqPmTask, HqBackflow, HqTowerSprayLog,
)


def import_hq_hvac(session):
    # Skip if already imported
    existing = session.query(HqHeatPump).count()
    if existing > 0:
        print(f"  HQ HVAC data already exists ({existing} heat pumps), skipping")
        return

    wb = get_workbook("Copy of HQ HVAC System.xlsx")
    if not wb:
        return

    # Heat Pumps - columnar layout
    if "Heat Pumps" in wb.sheetnames:
        ws = wb["Heat Pumps"]
        count = 0
        # Row 3 (index 2 in 0-based) has HP names across columns
        row3 = [ws.cell(3, col).value for col in range(1, 21)]
        row4 = [ws.cell(4, col).value for col in range(1, 21)]  # Make
        row5 = [ws.cell(5, col).value for col in range(1, 21)]  # Model

        for i, hp_text in enumerate(row3):
            if not hp_text:
                continue
            hp_str = safe_str(hp_text)
            if not hp_str or ":" not in hp_str:
                continue

            parts = hp_str.split(":", 1)
            unit_id = parts[0].strip()
            location = parts[1].strip() if len(parts) > 1 else None

            make_str = safe_str(row4[i])
            if make_str and make_str.startswith("Make:"):
                make_str = make_str[5:].strip()

            model_str = safe_str(row5[i])
            if model_str and model_str.startswith("Model:"):
                model_str = model_str[6:].strip()

            hp = HqHeatPump(
                unit_id=unit_id,
                location_desc=location,
                make=make_str,
                model=model_str,
            )
            session.add(hp)
            count += 1
        print(f"  Imported {count} heat pumps")

    # Issues
    if "Issues " in wb.sheetnames or "Issues" in wb.sheetnames:
        sheet_name = "Issues " if "Issues " in wb.sheetnames else "Issues"
        ws = wb[sheet_name]
        count = 0
        for row in ws.iter_rows(min_row=1, values_only=True):
            desc = safe_str(row[0])
            if not desc:
                continue
            issue = HqHvacIssue(description=desc)
            session.add(issue)
            count += 1
        print(f"  Imported {count} HVAC issues")

    # PM Tasks from standard sheets
    pm_sheets = {
        "WSHP": "WSHP",
        "CoolingTower": "CoolingTower",
        "Boiler": "Boiler",
        "MUA": "MUA",
        "Pumps": "Pumps",
        "ExhaustFans": "ExhaustFans",
    }
    total_pm = 0
    for sheet_name, category in pm_sheets.items():
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        for row in ws.iter_rows(min_row=2, values_only=True):
            task_desc = safe_str(row[1])
            if not task_desc:
                continue

            can_in_house = safe_str(row[3])
            task = HqPmTask(
                equipment_category=category,
                equipment_id=safe_str(row[0]),
                task_description=task_desc,
                frequency=safe_str(row[2]),
                can_in_house=(can_in_house and can_in_house.lower() == "yes"),
                last_pm_date=safe_date(row[4]) if len(row) > 4 else None,
                next_due_date=safe_date(row[5]) if len(row) > 5 else None,
                status=safe_str(row[6]) or "Not Started",
                notes=safe_str(row[7]) if len(row) > 7 else None,
            )
            session.add(task)
            total_pm += 1
    print(f"  Imported {total_pm} PM tasks")

    # Backflows
    if "Backflows" in wb.sheetnames:
        ws = wb["Backflows"]
        count = 0
        for row in ws.iter_rows(min_row=1, values_only=True):
            desc = safe_str(row[0])
            if not desc:
                continue
            bf = HqBackflow(location_desc=desc)
            session.add(bf)
            count += 1
        print(f"  Imported {count} backflows")

    # Tower & Spray Pump
    if "Tower & Spray Pump" in wb.sheetnames:
        ws = wb["Tower & Spray Pump"]
        count = 0
        for row in ws.iter_rows(min_row=1, values_only=True):
            desc = safe_str(row[0])
            if not desc:
                continue
            entry = HqTowerSprayLog(description=desc)
            session.add(entry)
            count += 1
        print(f"  Imported {count} tower/spray log entries")

    session.commit()
    wb.close()
