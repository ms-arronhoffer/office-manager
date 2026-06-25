import re
from seed.helpers import get_workbook, safe_str, safe_int
from app.models import OfficeTransition, TransitionChecklistItem


def classify_transition_type(text):
    if not text:
        return "closing"
    text = text.lower()
    if "new office" in text:
        return "new_office"
    if "moving" in text or "move to new" in text:
        return "moving"
    return "closing"


def parse_office_num_from_sheet(sheet_name, b5_value):
    # Try B5 first
    if b5_value:
        s = str(b5_value).strip().replace("#", "")
        match = re.match(r"(\d+)", s)
        if match:
            return int(match.group(1))

    # Try from sheet name
    match = re.match(r"#?(\d+)", sheet_name.strip())
    if match:
        return int(match.group(1))
    return None


def import_transitions(session, office_map):
    # Skip if already imported
    existing = session.query(OfficeTransition).count()
    if existing > 0:
        print(f"  Transitions already exist ({existing}), skipping")
        return

    wb = get_workbook("Copy of Closing, Moving, New Offices 2026-2025-2024.xlsx")
    if not wb:
        return

    count = 0
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]

        # Row 0 (A1): type classification
        type_text = safe_str(ws.cell(1, 1).value)
        transition_type = classify_transition_type(type_text)

        # Row 2 (A3): address
        address = safe_str(ws.cell(3, 1).value)

        # Row 4 (A5, B5): Office # and number
        b5 = ws.cell(5, 2).value
        office_num = parse_office_num_from_sheet(sheet_name, b5)

        # Determine status from sheet name
        status = "completed" if "DONE" in sheet_name.upper() else "in_progress"

        office_id = office_map.get(office_num) if office_num else None

        transition = OfficeTransition(
            office_id=office_id,
            office_number=office_num,
            transition_type=transition_type,
            address=address,
            status=status,
            sheet_name=sheet_name,
        )
        session.add(transition)
        session.flush()

        # Extract checklist items from rows 6+
        item_count = 0
        for row_num in range(6, ws.max_row + 1):
            vals = [ws.cell(row_num, col).value for col in range(1, min(5, ws.max_column + 1))]
            label = safe_str(vals[0]) if vals else None
            if not label:
                continue
            # Skip header-like rows
            if label.lower() in ("office #", "closing office", "moving office"):
                continue

            item = TransitionChecklistItem(
                transition_id=transition.id,
                item_label=label,
                response=safe_str(vals[1]) if len(vals) > 1 else None,
                additional_notes=safe_str(vals[2]) if len(vals) > 2 else None,
                extra_notes=safe_str(vals[3]) if len(vals) > 3 else None,
                sort_order=item_count,
            )
            session.add(item)
            item_count += 1

        count += 1

    session.commit()
    wb.close()
    print(f"  Imported {count} transitions")
