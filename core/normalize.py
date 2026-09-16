"""Turn a parsed table plus a column mapping into target rows + diagnostics.

    parsing.py  -> ParsedTable      (structure: what cells exist, where)
    llm.py      -> MappingResult    (semantics: which column means what)
    schema.py   -> TargetSchemaSpec (the shape the customer asked for)
    normalize.py-> normalized rows + diagnostics   <- you are here

Two rules govern everything below.

*Never silently drop data.* A row that fails validation is still emitted, with
the problem recorded on the row and aggregated into diagnostics. The caller
decides whether to reject it; we only decide how to describe it.

*Distinguish "no column" from "no value".* They imply different fixes -- remap
the file versus fill in rows 7, 12 and 40 -- so they are never collapsed.

Unlike its ancestor, which cleaned four hardcoded fields by *name*, the schema
here is user-defined and field names are arbitrary, so cleaning is keyed by
field *type*: `CLEANERS` holds one entry per `schema.VALID_FIELD_TYPES` member.
A type with no entry passes through whitespace-collapsed rather than raising,
so extending the type set can never take normalization offline.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Callable

from dateutil import parser as dateparser

from .schema import TargetField, TargetSchemaSpec

if TYPE_CHECKING:  # pragma: no cover - annotations only
    # Typing only: normalization reads these structures but never builds them,
    # so it has no load-order coupling to the mapper or the parser.
    from .llm import MappingResult
    from .parsing import ParsedTable


# --- Public data shapes ----------------------------------------------------- #

@dataclass
class FieldValue:
    """One target field in one row, plus why it looks the way it does."""

    value: str | None
    mapped: bool
    source_column: str | None = None
    reason: str | None = None


@dataclass
class NormalizedRowData:
    source_row: int                 # 1-based row number in the ORIGINAL sheet
    fields: dict[str, FieldValue]   # target field name -> value
    warnings: list[str]
    complete: bool                  # every required field has a value


@dataclass
class DiagnosticData:
    severity: str                   # "info" | "warning" | "error"
    code: str
    message: str
    column: str | None = None
    target_field: str | None = None
    rows: list[int] = field(default_factory=list)    # affected source rows


@dataclass
class SummaryData:
    total_rows: int
    complete_rows: int
    rows_with_warnings: int
    mapped_fields: list[str]
    unmapped_fields: list[str]


# Mirrors the mapper's own threshold, so the diagnostic explains ambiguity with
# the same number the mapper used to flag it.
LOW_CONFIDENCE_THRESHOLD: float = 0.60


# --- Shared patterns -------------------------------------------------------- #

# Deliberately permissive: a data-quality signal, not an RFC 5322 validator. It
# flags "jane@@x" without rejecting legal-but-unusual addresses.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_DIGITS_RE = re.compile(r"\d")
# "ext 14", "ext. 14", "x14", "extension 14" at the end of a number.
_EXTENSION_RE = re.compile(
    r"[\s,;]*(?:ext(?:ension)?\.?|x)\s*[:.]?\s*(?P<ext>\d{1,6})\s*$", re.IGNORECASE
)
# "LASTNAME, Firstname" -- a common export shape; consumers want natural order.
_LAST_FIRST_RE = re.compile(r"^\s*([^,]+),\s*([^,]+?)\s*$")

# ...but "Dr. Aiko Tanaka, PhD" is NOT inverted: the text after the comma is a
# credential, not a given name. Flipping it produced "PhD Dr. Aiko Tanaka",
# exactly the confident-but-wrong output diagnostics exist to prevent. Company
# suffixes are here for the same reason ("Acme, Inc" -> "Inc Acme"). Matched
# case- and punctuation-insensitively, so "Ph.D." and "PHD" both hit.
_NAME_SUFFIXES = {
    "jr", "sr", "ii", "iii", "iv", "v", "phd", "md", "dds", "dvm", "esq", "jd",
    "mba", "ma", "ms", "msc", "bsc", "rn", "np", "cpa", "pe", "pmp", "cfa",
    "emeritus", "ret", "inc", "llc", "ltd", "llp", "plc", "corp", "co", "gmbh",
}

# Field names are user-defined now, so the flip is gated on the field looking
# like a person's name. Ungated, a "Notes" cell ("Delivered, late") becomes
# "late Delivered" -- damage nobody spots, because it still reads like prose.
_NAME_SIGNALS = {
    "name", "names", "fullname", "firstname", "lastname", "surname", "forename",
    "contact", "person", "people", "recipient", "employee", "attendee",
    "author", "owner", "applicant", "patient", "student", "member", "customer",
    "client", "guest", "physician", "doctor",
}
_NAME_BLOCKERS = {
    "description", "desc", "notes", "note", "comment", "comments", "remark",
    "remarks", "company", "organization", "organisation", "org", "business",
    "employer", "vendor", "supplier", "account", "product", "address", "street",
    "city", "department", "team", "file", "filename", "project", "school",
    "university", "institution", "brand", "title", "subject",
}


def _looks_like_suffix(text: str) -> bool:
    """True when `text` is a credential/generational/company suffix, not a name."""
    return re.sub(r"[.\s]", "", text).lower() in _NAME_SUFFIXES


def _is_person_name_field(target: TargetField) -> bool:
    """Whether the "Last, First" flip applies to this field.

    The field's own name is decisive: "Company Name" carries both a signal
    (`name`) and a blocker (`company`), and the blocker must win. Only a name
    with no verdict falls through to the description, a weaker free-text signal.
    """
    for text in (target.name, target.description or ""):
        tokens = {t for t in re.split(r"[^a-z]+", text.lower()) if t}
        if tokens & _NAME_BLOCKERS:
            return False
        if tokens & _NAME_SIGNALS:
            return True
    return False


# --- Per-type cleaners ------------------------------------------------------ #
# Each takes the raw cell text (non-empty, already stripped by the parser) and
# the target field, and returns (value, warning|None). A warning never discards
# the value: the reviewer sees what the file said *and* what we think is wrong.

Cleaned = tuple[str | None, str | None]
Cleaner = Callable[[str, TargetField], Cleaned]


def _collapse(raw: str) -> str:
    return " ".join(raw.split())


def _clean_string(raw: str, target: TargetField) -> Cleaned:
    """Collapse whitespace; flip 'Last, First' for person-name fields only."""
    value = _collapse(raw)
    match = _LAST_FIRST_RE.match(value) if _is_person_name_field(target) else None
    if not match:
        return value, None
    last, first = match.group(1).strip(), match.group(2).strip()
    if _looks_like_suffix(first):
        return value, None      # a trailing credential is not an inverted name
    flipped = f"{first} {last}"
    return flipped, f"name reordered from {value!r} to {flipped!r}"


def _clean_email(raw: str, target: TargetField) -> Cleaned:
    """Lowercase and trim, keeping the value even when it looks wrong."""
    value = raw.strip().lower()
    if not _EMAIL_RE.match(value):
        return value, f"email {value!r} does not look like a valid address"
    return value, None


def _clean_phone(raw: str, target: TargetField) -> Cleaned:
    """Digits with an optional leading +; odd shapes kept as-is and reported.

    We standardise the common US 10/11-digit cases and otherwise keep what we
    were given: inventing a format is a silent misinterpretation.
    """
    text = raw.strip()

    # Pull a trailing extension off before counting digits. Folding it in
    # produced "555010220014" from "555-010-2200 ext. 14" -- a number that looks
    # valid and dials somewhere else entirely. Keep the base number and report
    # the extension instead of encoding it into the value.
    extension: str | None = None
    ext_match = _EXTENSION_RE.search(text)
    if ext_match:
        extension = ext_match.group("ext")
        text = text[: ext_match.start()].strip()
    ext_note = (
        f"extension {extension!r} was separated from the number and is not "
        f"represented in field '{target.name}'" if extension else None
    )

    digits = "".join(_DIGITS_RE.findall(text))
    if not digits:
        return text or raw.strip(), f"phone {raw.strip()!r} contains no digits"
    if text.startswith("+"):
        return f"+{digits}", ext_note
    if len(digits) == 10:
        return f"+1{digits}", ext_note
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}", ext_note
    note = f"phone {raw.strip()!r} has an unexpected length ({len(digits)} digits)"
    return digits, f"{note}; {ext_note}" if ext_note else note


# Currency symbols and grouping noise. A comma is dropped only in a true
# thousands position (three digits follow), so a European "12,5" is reported as
# unparseable rather than silently becoming 125.
_NUMERIC_NOISE_RE = re.compile(r"[\s _'’$£€¥₹¢]|(?<=\d),(?=\d{3}(?!\d))")


def _to_decimal(raw: str) -> Decimal | None:
    """Parse accounting-flavoured numeric text, or None if it is not a number."""
    text = raw.strip().replace("−", "-")            # unicode minus
    negative = False
    # Parens-as-negative is accounting notation, not a typo: "(1,250.00)" is
    # -1250.00 on every financial export we have seen; a trailing "-" likewise.
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1].strip()
    elif text.endswith("-"):
        negative, text = True, text[:-1].strip()
    text = _NUMERIC_NOISE_RE.sub("", text)
    try:
        value = Decimal(text) if text else None
    except (InvalidOperation, ValueError):
        return None
    if value is None or not value.is_finite():      # "NaN" is a valid Decimal
        return None
    return -value if negative else value


def _clean_number(raw: str, target: TargetField) -> Cleaned:
    """Strip currency symbols, thousands separators and parens-negatives."""
    value = _to_decimal(raw)
    if value is None:
        return _collapse(raw), f"number {_collapse(raw)!r} could not be parsed"
    # Plain decimal text, never scientific notation: a human reads this cell.
    return format(value, "f"), None


def _clean_integer(raw: str, target: TargetField) -> Cleaned:
    """As `number`, but whole. A fractional part is reported, never rounded off."""
    value = _to_decimal(raw)
    if value is None:
        return _collapse(raw), f"integer {_collapse(raw)!r} could not be parsed"
    if value == value.to_integral_value():
        return str(int(value)), None
    # Rounding would invent data the file never held; the reviewer decides
    # whether 3.7 meant 3 or 4.
    text = format(value, "f")
    return text, f"integer field received {text!r}, which has a fractional part"


# Numeric date forms: 3/4/2025, 03.04.2025, 2025-03-04.
_NUMERIC_DATE_RE = re.compile(r"^(\d{1,4})[/.\-](\d{1,2})[/.\-](\d{2,4})$")


def _clean_date(raw: str, target: TargetField) -> Cleaned:
    """Parse with dateutil and emit ISO `YYYY-MM-DD`.

    Day-first only on unambiguous evidence (a first component above 12);
    otherwise month-first, the dominant convention in the files we ingest, and
    the warning says so when the value could legitimately be either. A date
    read as 3 April when the file meant 4 March is the most expensive mistake
    this pipeline can make, and it is invisible downstream.
    """
    text = _collapse(raw)
    dayfirst = False
    ambiguity: str | None = None

    match = _NUMERIC_DATE_RE.match(text)
    if match:
        first, second = int(match.group(1)), int(match.group(2))
        if len(match.group(1)) == 4 or second > 12:
            pass                        # 2025-03-04 / 03-25-2025: month-first
        elif first > 12:
            dayfirst = True             # 25/03/2025 can only be day-first
        else:
            ambiguity = (
                f"date {text!r} is ambiguous (day and month are both <= 12); "
                "interpreted as month-first (MM/DD/YYYY)"
            )
    try:
        parsed = dateparser.parse(text, dayfirst=dayfirst)
    except (ValueError, OverflowError, TypeError):
        parsed = None
    if parsed is None:
        return text, f"date {text!r} could not be parsed"
    return parsed.date().isoformat(), ambiguity


_TRUE_WORDS = {"true", "t", "yes", "y", "1", "on"}
_FALSE_WORDS = {"false", "f", "no", "n", "0", "off"}


def _clean_boolean(raw: str, target: TargetField) -> Cleaned:
    """Map a true/false/yes/no/y/n/1/0/t/f vocabulary to "true"/"false"."""
    token = _collapse(raw).strip(".").lower()
    if token in _TRUE_WORDS:
        return "true", None
    if token in _FALSE_WORDS:
        return "false", None
    return _collapse(raw), f"boolean {_collapse(raw)!r} is not a true/false value"


# The registry that replaces the ancestor's per-field-NAME dispatch: keyed by
# field_type, so a schema of 200 customer-named columns needs no new code.
CLEANERS: dict[str, Cleaner] = {
    "string": _clean_string,
    "email": _clean_email,
    "phone": _clean_phone,
    "number": _clean_number,
    "integer": _clean_integer,
    "date": _clean_date,
    "boolean": _clean_boolean,
}


# --- Normalization ---------------------------------------------------------- #

def _ambiguity_reason(confidence: float, runner_up: float) -> str:
    """Explain *why* a mapping is ambiguous, in its own terms.

    The two causes need different wording: "uncertain (confidence 1.00)"
    because a runner-up scored 0.98 is self-contradictory, and a reviewer who
    reads one such warning learns to ignore all of them.
    """
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        return (
            f"the best match scored only {confidence:.2f}, below the "
            f"{LOW_CONFIDENCE_THRESHOLD:.2f} confidence threshold"
        )
    return (
        f"a second column scored nearly as well ({runner_up:.2f} vs "
        f"{confidence:.2f}), so the choice between them is not clear-cut"
    )


def normalize(
    schema: TargetSchemaSpec,
    table: ParsedTable,
    mapping: MappingResult,
) -> tuple[list[NormalizedRowData], list[DiagnosticData], SummaryData]:
    """Produce normalized rows, aggregated diagnostics, and a summary."""
    diagnostics: list[DiagnosticData] = []
    targets = [f for f in (schema.field(n) for n in schema.field_names) if f]
    headers = set(table.headers)

    def diag(severity: str, code: str, message: str, **kw: Any) -> None:
        diagnostics.append(DiagnosticData(severity, code, message, **kw))

    # Parse notes are (severity, code, message) tuples; promote them so the
    # caller gets one unified diagnostics list rather than two channels.
    for severity, code, message in table.notes:
        diag(severity, code, message)

    # ---- Mapping-level findings ---------------------------------------------
    # Driven by the schema, not by `mapping.mappings`: a field the mapper never
    # returned an entry for is still a field the customer asked for.
    bound: dict[str, str] = {}          # target field name -> source column
    for target in targets:
        cm = mapping.mappings.get(target.name)
        column = cm.source_column if cm is not None and cm.is_mapped else None
        # A mapping naming a column this file lacks (stale mapping, re-upload of
        # a different export) counts as unmapped: reporting it as "mapped, but
        # every row empty" sends the reviewer hunting for data never present.
        if column is not None and column not in headers:
            column = None
        if column is None:
            diag("error" if target.required else "info", "unmapped_target_field",
                 f"No usable source column is mapped to required field "
                 f"'{target.name}'. Every row will be missing it."
                 if target.required
                 else f"Optional field '{target.name}' has no source column.",
                 target_field=target.name)
            continue

        bound[target.name] = column
        if cm is not None and cm.ambiguous:
            alts = ", ".join(
                f"{a.source_column} ({a.confidence:.2f})" for a in cm.alternatives
            )
            runner_up = cm.alternatives[0].confidence if cm.alternatives else 0.0
            diag("warning", "ambiguous_mapping",
                 f"Mapped '{column}' -> '{target.name}', but "
                 f"{_ambiguity_reason(cm.confidence, runner_up)}."
                 + (f" Alternatives: {alts}." if alts else "")
                 + " Confirm before trusting this column.",
                 column=column, target_field=target.name)

    for col in mapping.unmapped_source_columns:
        diag("info", "unmapped_source_column",
             f"Source column '{col}' was not mapped to any field in schema "
             f"'{schema.name}'; its data is not represented in the output.",
             column=col)

    # ---- Row-level normalization --------------------------------------------
    rows: list[NormalizedRowData] = []
    missing_required: dict[str, list[int]] = defaultdict(list)
    invalid_values: dict[str, list[int]] = defaultdict(list)
    rows_with_warnings = 0
    complete_rows = 0
    required_names = [t.name for t in targets if t.required]

    for prow in table.rows:
        values: dict[str, FieldValue] = {}
        warnings: list[str] = []

        for target in targets:
            column = bound.get(target.name)

            # `mapped=False`: the file had no usable column for this field. NOT
            # the same as an empty cell, and never merged with it -- this one is
            # fixed by remapping, the other by editing the source file.
            if column is None:
                values[target.name] = FieldValue(
                    None, False, None, "no source column matched this field")
                continue

            raw = prow.cells.get(column)

            # `mapped=True, value=None`: the column exists, this row is blank.
            if raw is None or not str(raw).strip():
                values[target.name] = FieldValue(
                    None, True, column, "source cell was empty")
                if target.required:
                    missing_required[target.name].append(prow.source_row)
                    warnings.append(f"required field '{target.name}' is empty")
                continue

            cleaner = CLEANERS.get(target.field_type)
            value, warning = (cleaner(str(raw), target) if cleaner
                              else (_collapse(str(raw)), None))
            if warning:
                warnings.append(warning)
                invalid_values[target.name].append(prow.source_row)
            values[target.name] = FieldValue(value, True, column)

        complete = all(values[name].value is not None for name in required_names)
        complete_rows += int(complete)
        rows_with_warnings += int(bool(warnings))
        # Emitted unconditionally: a problematic row is still the customer's
        # data, and only the caller can decide whether it is acceptable.
        rows.append(NormalizedRowData(prow.source_row, values, warnings, complete))

    # ---- Aggregate row findings ---------------------------------------------
    # Once per field, carrying the affected row numbers, rather than once per
    # row: a 5000-row file with one bad column yields ONE diagnostic instead of
    # 5000 that no reviewer will read.
    for name, row_nums in missing_required.items():
        diag("warning", "missing_required_value",
             f"{len(row_nums)} row(s) are missing required field '{name}'.",
             column=bound.get(name), target_field=name, rows=sorted(row_nums))
    for name, row_nums in invalid_values.items():
        diag("warning", "value_needs_review",
             f"{len(row_nums)} row(s) had a '{name}' value that was reformatted "
             "or failed validation; see row warnings.",
             column=bound.get(name), target_field=name, rows=sorted(row_nums))

    return rows, diagnostics, SummaryData(
        total_rows=len(rows),
        complete_rows=complete_rows,
        rows_with_warnings=rows_with_warnings,
        mapped_fields=[t.name for t in targets if t.name in bound],
        unmapped_fields=[t.name for t in targets if t.name not in bound],
    )
