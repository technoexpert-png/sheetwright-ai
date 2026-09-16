"""Deterministic structural parsing of uploaded spreadsheets.

Ingestion is deliberately split in two. **Structure** (this module) turns
arbitrary CSV/XLSX bytes into a rectangular table: repair merged cells, find the
row that is actually the header, clean the labels, square up ragged rows. Every
decision is deterministic and explainable, so a file always parses the same way
and failures are debuggable without a model in the loop. **Semantics**
(`core/llm.py`) decides that "E-Mail Addr." means `email` — a judgement call,
and the only place the LLM is trusted. Keeping them apart means an LLM outage
degrades *mapping*, not *parsing*, and a parsing bug can never be mistaken for
a bad model response.

Every emitted value is `str | None`: type inference (dates, phone numbers,
leading-zero IDs, currency) belongs to normalization, which knows the column's
canonical meaning. Guessing here would destroy information irreversibly —
"0123" must not silently become 123.

Recoverable weirdness is never fatal; it is repaired and recorded in
`ParsedTable.notes`. `ParseError` is reserved for "this is not a table".
"""

from __future__ import annotations

import codecs
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

import openpyxl

# (severity, code, message), severity in {"info","warning","error"}. A plain
# tuple keeps parsing free of any dependency on the pydantic layer; the pipeline
# lifts these into `Diagnostic`s.
Note = tuple[str, str, str]
Grid = list[list[str | None]]

_DELIMITED_EXT = {".csv", ".tsv", ".txt"}
_EXCEL_EXT = {".xlsx", ".xlsm"}

_HEADER_SCAN_ROWS = 10      # preambles are short; scanning deeper invites false positives
_MAX_HEADER_LEN = 60        # anything longer is prose (a blurb row), not a label
_QUOTES = "\"'`‘’“”"

# Markers of a *value* rather than a *label*: a header cell essentially never
# holds an email, a date or a phone number. Used as a veto in header scoring.
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{6,}\d")


class ParseError(Exception):
    """Raised when the bytes cannot be turned into a table at all."""


@dataclass
class ParsedRow:
    source_row: int                     # 1-based row number in the ORIGINAL sheet
    cells: dict[str, str | None]        # cleaned_header -> value; "" becomes None


@dataclass
class ParsedTable:
    headers: list[str]                  # cleaned, de-duplicated, in order
    # Header text before de-duplication and placeholder naming, so a caller can
    # see that 'Email_2' was really 'Email' and 'column_4' was really blank.
    # Surrounding whitespace is already trimmed by cell coercion.
    original_headers: list[str]
    rows: list[ParsedRow]
    header_row_number: int              # 1-based
    sheet_name: str | None
    notes: list[Note] = field(default_factory=list)


# --- Value cleaning -------------------------------------------------------- #

def _clean_value(value: Any) -> str | None:
    """Coerce one cell to a stripped string, or None when it holds nothing."""
    if value is None:
        return None
    # bool before the numeric branch: bool subclasses int, so True would
    # otherwise serialise as "1" and lose its meaning.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        # Excel models every date as a datetime; midnight is a format artefact,
        # not something the user typed, so a pure date stays a pure date.
        return value.date().isoformat() if value.time() == time(0, 0) else value.isoformat(sep=" ")
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, (float, Decimal)):
        # Excel returns 123.0 for an integer cell; "123.0" would corrupt IDs, zip
        # codes and phone numbers. The magnitude guard avoids int() on inf/huge.
        number = float(value)
        if number.is_integer() and abs(number) < 1e15:
            return str(int(number))
        value = number
    text = str(value).strip()
    return text or None                 # whitespace-only is absence, not a value


# --- Header detection and cleaning ----------------------------------------- #

def _looks_numeric(text: str) -> bool:
    try:
        float(text.replace(",", "").replace("$", "").replace("%", "").strip())
        return True
    except ValueError:
        return False


def _looks_like_data(text: str) -> bool:
    if len(text) > _MAX_HEADER_LEN:
        return True
    return bool(_EMAIL_RE.search(text) or _DATE_RE.search(text) or _PHONE_RE.search(text))


def _score_header_row(row: Sequence[str | None], width: int) -> float:
    """Score a candidate header row; higher is more header-like."""
    values = [v for v in row if v]
    if not values:
        return float("-inf")
    fill = len(values) / max(width, 1)                                   # headers span the table
    short = sum(1 for v in values if len(v) <= _MAX_HEADER_LEN) / len(values)
    numeric = sum(1 for v in values if _looks_numeric(v)) / len(values)  # numbers mean data
    duplicated = 1.0 - len({v.lower() for v in values}) / len(values)    # repeats are suspicious
    score = 2.0 * fill + 1.5 * short - 2.0 * numeric - 1.0 * duplicated
    if len(values) == 1:
        score -= 1.0        # one populated cell is a title, never a header
    if any(_looks_like_data(v) for v in values):
        # Flat and decisive. Ratios alone lose to a fully populated data row
        # whenever the real header has an empty column — common in exports.
        score -= 1.5
    return score


def _detect_header_row(grid: Grid) -> int:
    """0-based index of the most header-like of the first non-empty rows.

    Real exports open with a title, a date stamp, maybe a blurb, so row 1 is a
    bad assumption. The small per-row decay breaks ties toward the top: the
    first plausible header *is* the header, everything under it is data.
    """
    width = max((len(r) for r in grid), default=0)
    best_index, best_score = -1, float("-inf")
    examined = 0
    for index, row in enumerate(grid):
        if not any(row):
            continue                    # blank spacer rows are never the header
        examined += 1
        if examined > _HEADER_SCAN_ROWS:
            break
        score = _score_header_row(row, width) - 0.15 * examined
        if score > best_score:
            best_index, best_score = index, score
    if best_index < 0:
        raise ParseError("No non-empty rows found in the file.")
    return best_index


def _clean_header_text(raw: str | None) -> str:
    if raw is None:
        return ""
    text = re.sub(r"\s+", " ", raw).strip()   # wrapped/merged labels carry newlines
    text = text.strip(_QUOTES).strip()        # over-quoted CSV headers arrive as '"Email"'
    if text.endswith(":"):
        text = text[:-1].rstrip()             # "Email:" and "Email" are one column
    return text


def _build_headers(raw_row: Sequence[str | None], notes: list[Note]) -> tuple[list[str], list[str]]:
    """Clean the labels, keeping the untouched originals for provenance."""
    original = ["" if v is None else str(v) for v in raw_row]
    cleaned: list[str] = []
    blanks: list[int] = []
    duplicates: list[str] = []
    seen: dict[str, int] = {}
    for index, raw in enumerate(raw_row):
        name = _clean_header_text(raw)
        if not name:
            name = f"column_{index + 1}"      # 1-based: matches the spreadsheet column position
            blanks.append(index + 1)
        key = name.lower()                    # collide case-insensitively: "Email" vs "email"
        if key in seen:
            seen[key] += 1
            candidate = f"{name}_{seen[key]}"
            while candidate.lower() in seen:  # a literal "Email_2" may already exist
                seen[key] += 1
                candidate = f"{name}_{seen[key]}"
            duplicates.append(name)
            name = candidate
        seen.setdefault(name.lower(), 1)
        cleaned.append(name)
    if blanks:
        notes.append(("warning", "blank_header",
                      f"{len(blanks)} blank header cell(s) named by position "
                      f"(columns {', '.join(map(str, blanks))})."))
    if duplicates:
        notes.append(("warning", "duplicate_header",
                      f"Duplicate header(s) suffixed to stay unique: "
                      f"{', '.join(sorted(set(duplicates)))}."))
    return cleaned, original


# --- Table assembly -------------------------------------------------------- #

def _header_span(grid: Grid, header_index: int) -> list[str | None]:
    """The header row minus dead trailing columns.

    Width comes from the header row itself, not the widest data row, so surplus
    cells get reported instead of silently growing the schema. A trailing column
    is dropped only when its header *and* every cell beneath it are empty; Excel
    and hand-edited CSVs carry those constantly and naming them column_8,
    column_9 ... would pollute the mapping prompt with noise.
    """
    header_row: list[str | None] = list(grid[header_index])
    while header_row and header_row[-1] is None:
        column = len(header_row) - 1
        if any(column < len(r) and r[column] for r in grid[header_index + 1:]):
            break
        header_row.pop()
    return header_row


def _build_table(grid: Grid, sheet_name: str | None, notes: list[Note]) -> ParsedTable:
    if not any(any(row) for row in grid):
        raise ParseError("No data found: every cell in the file is empty.")

    header_index = _detect_header_row(grid)
    preamble = [i + 1 for i in range(header_index) if any(grid[i])]
    if preamble:
        notes.append(("info", "preamble_skipped",
                      f"Treated {len(preamble)} row(s) above the header as preamble "
                      f"(rows {', '.join(map(str, preamble))})."))

    headers, original_headers = _build_headers(_header_span(grid, header_index), notes)
    if not headers:
        raise ParseError("The detected header row is empty; no columns could be determined.")

    rows: list[ParsedRow] = []
    blank_rows = 0
    ragged: list[int] = []
    for index in range(header_index + 1, len(grid)):
        raw = grid[index]
        # Row numbers come from the file, never the output position: blank and
        # preamble rows still consume one, so `source_row` always points at the
        # line a reviewer sees when they open the sheet.
        row_number = index + 1
        if not any(raw):
            blank_rows += 1
            continue
        if len(raw) > len(headers) and any(raw[len(headers):]):
            ragged.append(row_number)
        # Short rows pad with None; long rows are truncated to the header width,
        # the surplus reported rather than invented into a fabricated column.
        cells = {name: (raw[i] if i < len(raw) else None) for i, name in enumerate(headers)}
        rows.append(ParsedRow(source_row=row_number, cells=cells))

    if blank_rows:
        notes.append(("info", "blank_rows_skipped",
                      f"Skipped {blank_rows} fully blank row(s) below the header."))
    if ragged:
        shown = ", ".join(map(str, ragged[:10])) + (" ..." if len(ragged) > 10 else "")
        notes.append(("warning", "extra_cells",
                      f"{len(ragged)} row(s) had more cells than the {len(headers)} header(s); "
                      f"the surplus values were dropped (rows {shown})."))
    if not rows:
        raise ParseError("No data rows found below the detected header row.")

    return ParsedTable(headers=headers, original_headers=original_headers, rows=rows,
                       header_row_number=header_index + 1, sheet_name=sheet_name, notes=notes)


# --- Format readers -------------------------------------------------------- #

def _decode(data: bytes) -> str:
    """Best-effort text decode; latin-1 never raises, so it is the safety net."""
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16")
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ParseError("Could not decode the file as text.")


def _read_delimited(data: bytes, extension: str, notes: list[Note]) -> Grid:
    text = _decode(data).replace("\x00", "")     # stray NULs make the csv module raise
    if not text.strip():
        raise ParseError("The file is empty.")
    if extension == ".tsv":
        delimiter = "\t"
    else:
        try:
            delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","                      # single-column files defeat the sniffer
        if delimiter != ",":
            notes.append(("info", "delimiter_detected",
                          f"Parsed with {delimiter!r} as the field delimiter."))
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
        return [[_clean_value(cell) for cell in row] for row in reader]
    except csv.Error as exc:
        raise ParseError(f"Malformed delimited file: {exc}") from exc


def _sheet_to_grid(worksheet: Any) -> tuple[Grid, int]:
    """Read a worksheet into a grid, expanding merged ranges. -> (grid, n_expanded)."""
    grid: Grid = [[_clean_value(v) for v in row] for row in worksheet.iter_rows(values_only=True)]

    # --- MERGED CELLS ------------------------------------------------------ #
    # xlsx (and openpyxl with it) stores a merged range's value ONLY in the
    # top-left anchor; every other cell in the rectangle reads back as None. A
    # human sees the value filling the whole block, so parsing it as holes means
    # parsing something other than the file the user believes they uploaded:
    #   * a "Contact Details" band merged across A3:B3 leaves a blank header
    #     slot that we would then misname column_2;
    #   * a company merged down C4:C5 blanks the company on row 5, which
    #     downstream looks exactly like missing required data.
    # So we paint the anchor across the whole rectangle. This is a faithful
    # de-normalisation, not a guess: the file itself asserts those cells hold
    # that value. Ranges with an empty anchor carry no information and are left
    # alone. Bounds are clamped because a merged range may legally extend past
    # the last row/column that actually contains data.
    expanded = 0
    for cell_range in worksheet.merged_cells.ranges:
        top, left = cell_range.min_row - 1, cell_range.min_col - 1
        if top >= len(grid) or left >= len(grid[top]):
            continue
        anchor = grid[top][left]
        if anchor is None:
            continue
        for row_index in range(top, min(cell_range.max_row, len(grid))):
            row = grid[row_index]
            for column_index in range(left, min(cell_range.max_col, len(row))):
                row[column_index] = anchor
        expanded += 1
    return grid, expanded


def _read_xlsx(data: bytes, notes: list[Note]) -> tuple[Grid, str]:
    try:
        # data_only=True returns cached formula *results*; without it every
        # computed cell would arrive as the literal "=SUM(...)" string.
        workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    except Exception as exc:  # openpyxl raises a zoo of types on corrupt input
        raise ParseError(
            f"Could not open the workbook (corrupt or not a real .xlsx): {exc}"
        ) from exc
    try:
        for worksheet in workbook.worksheets:
            if worksheet.sheet_state != "visible":
                continue                  # hidden sheets are lookup tables, not the payload
            grid, expanded = _sheet_to_grid(worksheet)
            if not any(any(row) for row in grid):
                continue                  # empty sheet: try the next one
            if expanded:
                notes.append(("warning", "merged_cells_expanded",
                              f"Expanded {expanded} merged cell range(s) on sheet "
                              f"'{worksheet.title}': each anchor value was propagated across "
                              f"its full range."))
            return grid, worksheet.title
    finally:
        workbook.close()
    raise ParseError("The workbook contains no visible worksheet with any data.")


# --- Public entry point ----------------------------------------------------- #

def parse_spreadsheet(filename: str, data: bytes) -> ParsedTable:
    """Parse upload bytes into a rectangular table, dispatching on extension.

    Raises `ParseError` for unsupported extensions, corrupt/unreadable files and
    files with no detectable data rows.
    """
    if not data:
        raise ParseError("The uploaded file is empty.")
    extension = Path(filename or "").suffix.lower()
    notes: list[Note] = []
    if extension in _DELIMITED_EXT:
        grid: Grid = _read_delimited(data, extension, notes)
        sheet_name: str | None = None
    elif extension in _EXCEL_EXT:
        grid, sheet_name = _read_xlsx(data, notes)
    elif extension == ".xls":
        # Called out separately: the legacy binary format is one re-save away.
        raise ParseError("Legacy .xls files are not supported. Re-save the file as .xlsx.")
    else:
        raise ParseError(
            f"Unsupported file type {extension or filename!r}. Expected one of: "
            f"{', '.join(sorted(_DELIMITED_EXT | _EXCEL_EXT))}."
        )
    return _build_table(grid, sheet_name, notes)
