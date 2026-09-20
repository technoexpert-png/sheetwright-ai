"""Serialize normalized rows into the files a customer downloads.

Export is deliberately *data only*. Diagnostics, warnings and the mapped/empty
distinction are an API concern: they belong in the review UI, where someone can
act on them, not in a CSV that gets loaded straight into a CRM. The one piece
of provenance that does survive is `_source_row`, so any output line can be
traced back to the line of the upload it came from.

Every value arrives here as `str | None` (normalization owns interpretation),
and `None` is written as a genuinely empty cell -- never the string "None",
which is the kind of artefact that ends up in a mail merge.
"""

from __future__ import annotations

import csv
import io
import json
import re

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from .normalize import NormalizedRowData
from .schema import TargetSchemaSpec

# Appended as the LAST column, never the first: the schema's own field order is
# what the customer designed and what their downstream importer expects by
# position. A trailing technical column can be ignored or dropped without
# disturbing it.
SOURCE_ROW_COLUMN = "_source_row"

CONTENT_TYPES: dict[str, str] = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "json": "application/json",
}

# Excel rejects sheet names over 31 characters or containing []:*?/\.
_SHEET_NAME_BAD = re.compile(r"[\[\]:*?/\\]")
_MAX_COL_WIDTH = 48


def _headers(schema: TargetSchemaSpec) -> list[str]:
    """Target field names in schema position order, plus the provenance column."""
    return [*schema.field_names, SOURCE_ROW_COLUMN]


def _value(row: NormalizedRowData, name: str) -> str | None:
    """The plain value for one field, with "no column" and "empty" both -> None.

    Export is where the two legitimately collapse: a blank cell is a blank cell
    to a spreadsheet. The distinction is preserved for the review API, which is
    the place where it can still be acted on.
    """
    held = row.fields.get(name)
    return held.value if held is not None else None


def to_csv(schema: TargetSchemaSpec, rows: list[NormalizedRowData]) -> bytes:
    """UTF-8 CSV *with a BOM*.

    The BOM is not decoration. Excel on Windows opens a BOM-less UTF-8 CSV in
    the local ANSI code page, so "Zoë" becomes "ZoÃ«" and the customer's first
    impression of the product is mangled data. Every other consumer (pandas,
    Python's csv, Google Sheets) skips the BOM silently, so it is the safe
    default rather than a trade-off.
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(_headers(schema))
    for row in rows:
        cells = [_value(row, name) for name in schema.field_names]
        writer.writerow([*(c if c is not None else "" for c in cells), row.source_row])
    return buffer.getvalue().encode("utf-8-sig")


def to_xlsx(schema: TargetSchemaSpec, rows: list[NormalizedRowData]) -> bytes:
    """XLSX with a bold frozen header row and readable column widths."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = (_SHEET_NAME_BAD.sub(" ", schema.name).strip() or "Data")[:31]

    headers = _headers(schema)
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    # Freeze below the header so it stays visible while scrolling 5000 rows.
    sheet.freeze_panes = "A2"

    widths = [len(h) for h in headers]
    for row in rows:
        values: list[str | int | None] = [
            _value(row, name) for name in schema.field_names
        ]
        # Written as text, not coerced to numbers: normalization already decided
        # what each value means, and letting Excel re-guess turns "0123" into
        # 123 and a long phone number into 5.55011e+09. `_source_row` is a real
        # number, so it stays one and sorts correctly.
        sheet.append([*values, row.source_row])
        for index, value in enumerate([*values, str(row.source_row)]):
            widths[index] = max(widths[index], len(value or ""))

    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = min(
            max(width + 2, 10), _MAX_COL_WIDTH
        )

    payload = io.BytesIO()
    workbook.save(payload)
    return payload.getvalue()


def to_json(schema: TargetSchemaSpec, rows: list[NormalizedRowData]) -> bytes:
    """JSON with the schema echoed alongside flat scalar field values.

    The schema travels with the data so a consumer can tell an empty optional
    field from one the schema never had, without a second request.
    """
    document = {
        "schema": {
            "name": schema.name,
            "description": schema.description,
            "fields": [
                {
                    "name": f.name,
                    "field_type": f.field_type,
                    "required": f.required,
                    "description": f.description,
                    "position": f.position,
                }
                for f in sorted(schema.fields, key=lambda f: f.position)
            ],
        },
        "rows": [
            {
                "source_row": row.source_row,
                "complete": row.complete,
                # Plain scalars, not FieldValue objects: this is the export
                # format, not the review API.
                "fields": {n: _value(row, n) for n in schema.field_names},
            }
            for row in rows
        ],
    }
    # ensure_ascii=False keeps names legible ("Zoë" rather than "Zo\\u00eb");
    # the bytes are UTF-8, the encoding every JSON consumer must support.
    return json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")


_EXPORTERS = {"csv": to_csv, "xlsx": to_xlsx, "json": to_json}


def export(
    fmt: str, schema: TargetSchemaSpec, rows: list[NormalizedRowData]
) -> tuple[bytes, str]:
    """Dispatch on format name, returning (payload, content_type)."""
    key = (fmt or "").strip().lower().lstrip(".")
    exporter = _EXPORTERS.get(key)
    if exporter is None:
        raise ValueError(
            f"Unknown export format {fmt!r}; expected one of: "
            f"{', '.join(sorted(_EXPORTERS))}."
        )
    return exporter(schema, rows), CONTENT_TYPES[key]
