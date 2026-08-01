/**
 * Parser for spreadsheet paste and CSV used by bulk-insert flows.
 *
 * Accepts tab-separated (what Excel and Sheets put on the clipboard) or
 * comma-separated text, with optional double-quoted fields.
 */

/** Split one line into fields, honouring `"` quoting and `""` escapes. */
function splitLine(line: string, delimiter: string): string[] {
  const fields: string[] = [];
  let current = '';
  let inQuotes = false;

  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (inQuotes) {
      if (char === '"') {
        if (line[i + 1] === '"') {
          current += '"';
          i += 1;
        } else {
          inQuotes = false;
        }
      } else {
        current += char;
      }
    } else if (char === '"') {
      inQuotes = true;
    } else if (char === delimiter) {
      fields.push(current);
      current = '';
    } else {
      current += char;
    }
  }
  fields.push(current);
  return fields.map((f) => f.trim());
}

/**
 * Turn pasted text into one object per line, keyed by `columnKeys` in order.
 *
 * A leading header row is skipped when its first cell matches the first column
 * key (case- and separator-insensitive), so pasting with headers still works.
 */
export function parseDelimitedRows(
  text: string,
  columnKeys: string[],
): Record<string, string>[] {
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l !== '');
  if (lines.length === 0) return [];

  const delimiter = lines[0].includes('\t') ? '\t' : ',';
  const normalize = (s: string) => s.toLowerCase().replace(/[\s_-]/g, '');

  const rows = lines.map((line) => splitLine(line, delimiter));
  const firstCell = normalize(rows[0][0] ?? '');
  const looksLikeHeader =
    firstCell === normalize(columnKeys[0] ?? '') ||
    rows[0].every((cell, i) => i >= columnKeys.length || normalize(cell) === normalize(columnKeys[i]));
  const dataRows = looksLikeHeader && rows.length > 1 ? rows.slice(1) : rows;

  return dataRows.map((cells) => {
    const row: Record<string, string> = {};
    columnKeys.forEach((key, i) => {
      row[key] = cells[i] ?? '';
    });
    return row;
  });
}

export default parseDelimitedRows;
