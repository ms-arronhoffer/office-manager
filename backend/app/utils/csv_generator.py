import io
import csv
from typing import Any


def generate_csv(headers: list[str], rows: list[list[Any]]) -> io.StringIO:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([str(v) if v is not None else "" for v in row])
    output.seek(0)
    return output
