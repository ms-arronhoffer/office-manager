import os
import re
from datetime import datetime, date
from openpyxl import load_workbook

# dateutil is used as a final fallback for date parsing
try:
    from dateutil.parser import parse as _dateutil_parse
    _HAS_DATEUTIL = True
except ImportError:
    _HAS_DATEUTIL = False


DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# Sentinel strings that should never be treated as dates
_NON_DATE_STRINGS = frozenset({
    "??", "?", "n/a", "na", "tbd", "none", "---", "--", "-", "updated",
    "see lease", "per lease", "ongoing", "month to month", "mtm",
})


def safe_str(val):
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def safe_int(val):
    if val is None:
        return None
    try:
        return int(float(str(val).strip().replace("#", "")))
    except (ValueError, TypeError):
        return None


def safe_float(val):
    if val is None:
        return None
    try:
        s = str(val).strip().replace("$", "").replace(",", "")
        return float(s)
    except (ValueError, TypeError):
        return None


def safe_date(val):
    """Convert val to a date object, returning None on failure.

    Accepts:
    - datetime / date objects (direct conversion)
    - strings: tries common Excel date formats, then dateutil as fallback
    """
    if val is None:
        return None

    # Native Python date/datetime
    if isinstance(val, datetime):
        d = val.date()
        return d if 1900 <= d.year <= 2100 else None
    if isinstance(val, date):
        return val if 1900 <= val.year <= 2100 else None

    s = str(val).strip()
    if not s:
        return None
    # Reject obvious non-date sentinels
    if s.lower() in _NON_DATE_STRINGS or s.startswith("---"):
        return None

    # Strip trailing garbage after the date portion (e.g. ", Invoice 232191129")
    # Keep only the part before the first comma that looks like date text
    date_candidate = s.split(",")[0].strip()

    # Try common explicit formats first (fast path)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y",
                "%B %d, %Y", "%b %d, %Y", "%B %Y", "%b %Y"):
        try:
            d = datetime.strptime(date_candidate, fmt).date()
            return d if 1900 <= d.year <= 2100 else None
        except ValueError:
            continue

    # dateutil fallback — handles ambiguous formats gracefully
    if _HAS_DATEUTIL:
        try:
            d = _dateutil_parse(date_candidate, fuzzy=False).date()
            return d if 1900 <= d.year <= 2100 else None
        except Exception:
            pass

    return None


def parse_notice_days(notice_str):
    """Extract integer days from strings like '90 Days', '180-days', '60-Days'."""
    if not notice_str:
        return None
    match = re.search(r"(\d+)", str(notice_str))
    if match:
        return int(match.group(1))
    return None


def parse_office_number_from_name(lease_name):
    """Parse leading office number from a lease name like '063 - Dayton' → 63."""
    if not lease_name:
        return None
    match = re.match(r"(\d+)", str(lease_name).strip())
    if match:
        return int(match.group(1))
    return None


def is_row_empty(row_values):
    return all(v is None or str(v).strip() == "" for v in row_values)


def get_workbook(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        print(f"  [SKIP] File not found: {path}")
        return None
    return load_workbook(path, data_only=True)
