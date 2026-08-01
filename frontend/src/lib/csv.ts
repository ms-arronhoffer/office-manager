/**
 * Client-side CSV export for the rows a user has selected in a table.
 *
 * Server-side `/export` endpoints stream the whole collection; this covers the
 * "just the rows I picked" case without a round trip.
 */

export interface CsvColumn<T> {
  header: string;
  value: (item: T) => string | number | null | undefined;
}

/**
 * Quote a value for CSV.
 *
 * Cells beginning with `=`, `+`, `-`, `@`, tab or CR are prefixed with a single
 * quote so spreadsheet applications treat them as text rather than executing
 * them as formulas (CSV injection).
 */
function escapeCell(value: string | number | null | undefined): string {
  const raw = value == null ? '' : String(value);
  const safe = /^[=+\-@\t\r]/.test(raw) ? `'${raw}` : raw;
  return `"${safe.replace(/"/g, '""')}"`;
}

/** Build a CSV document from `columns` and `rows`. */
export function toCsv<T>(columns: CsvColumn<T>[], rows: T[]): string {
  const lines = [columns.map((c) => escapeCell(c.header)).join(',')];
  for (const row of rows) {
    lines.push(columns.map((c) => escapeCell(c.value(row))).join(','));
  }
  return lines.join('\r\n');
}

/** Build a CSV from `rows` and trigger a browser download. */
export function exportRowsToCsv<T>(
  filename: string,
  columns: CsvColumn<T>[],
  rows: T[],
): void {
  // Leading BOM so Excel detects UTF-8 and renders accented characters.
  const blob = new Blob(['\uFEFF', toCsv(columns, rows)], {
    type: 'text/csv;charset=utf-8',
  });
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
  } finally {
    URL.revokeObjectURL(url);
  }
}

export default exportRowsToCsv;
