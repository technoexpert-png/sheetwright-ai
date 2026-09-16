"""Column mapping: source spreadsheet headers -> a *user-defined* target schema.

`core/parsing.py` decides what the table *is*; this module decides what its
columns *mean* — that "E-Mail Addr." is the customer's `email` field. It is the
only place a model is trusted, and the only place allowed to be unsure.

The hard part is that the target schema is not ours: every org edits its own, so
a field is just a `(name, field_type, required, description)` tuple we have
never seen. Nothing here may hardcode a field name, so it reasons over the two
signals a human would use — (1) what the field is *called and described* versus
what the column is called, and (2) what the field's *type* implies its values
look like versus what the sampled values actually look like.

Two implementations sit behind one interface. `MockColumnMapper` is
deterministic and offline, and is the default: the service and its tests run
with no API key, no network and no cost — a real heuristic, not a stub.
`AnthropicColumnMapper` asks Claude, constrained to a JSON schema via tool use,
so the answer is parsed, never scraped out of prose.

One interface, because everything downstream consumes `MappingResult` only:
swapping providers is a config change and the output contract keeps its shape
either way. That is also what makes the real mapper safe to degrade — when the
API fails we fall back to the mock and *say so* in `provider`, rather than
failing the upload or quietly claiming an LLM did the work.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Protocol

from dateutil import parser as date_parser

from config import settings
from core.schema import TargetField, TargetSchemaSpec

logger = logging.getLogger(__name__)

# Tuning. Deliberately conservative: it is cheaper for a human to confirm an
# ambiguous mapping than to discover a wrong one after the data is imported.
NAME_WEIGHT = 0.60              # what the column is called
CONTENT_WEIGHT = 0.40           # what the column contains
AGREEMENT_BONUS = 0.10          # both signals agreeing beats their sum
DESC_TERM_WEIGHT = 0.45         # description terms count, just below name terms
SYNONYM_DISCOUNT = 0.90         # a synonym is nearly as good as the word itself
ABBREV_DISCOUNT = 0.80          # 'Dept' -> 'department', 'Addr' -> 'address'
STRING_EVIDENCE_CAP = 0.50      # free text is never strong content evidence
NO_SAMPLE_DISCOUNT = 0.90       # header match with no values to corroborate it
MIN_CONFIDENCE = 0.25           # below this, a column is not a candidate at all
NAME_FLOOR = 0.34               # the header must be this plausible...
STRONG_CONTENT = 0.90           # ...unless the values are overwhelmingly right
CONTENT_ONLY_CONFIDENCE = 0.70  # a 100%-email column *is* the email column
LOW_CONFIDENCE = 0.60           # below this, flag for human review
CLOSE_RUNNER_UP = 0.15          # runner-up this near the winner -> ambiguous
MAX_ALTERNATIVES = 2
SAMPLE_ROWS_IN_PROMPT = 5

# Heuristic prior, NOT domain knowledge: recurring business-vocabulary clusters
# that people name fields after. Kept tiny on purpose — the real signal is the
# customer's own field name and description, and anything domain-specific is the
# model's job rather than this table's.
_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("name", "contact", "person"),
    ("email", "mail"),
    ("phone", "tel", "telephone", "mobile", "cell"),
    ("company", "org", "organization", "organisation", "employer", "account"),
    ("price", "cost", "amount"),
    ("sku", "code", "id", "item"),
    ("quantity", "qty", "units", "count", "stock"),
    ("date", "on", "when", "created"),
)
_SYNONYMS: dict[str, tuple[str, ...]] = {
    word: tuple(w for w in group if w != word) for group in _SYNONYM_GROUPS for word in group
}

# Filler. Descriptions are prose, so without this every field would "match" any
# header sharing a preposition.
_STOPWORDS = frozenset({
    "a", "an", "and", "any", "as", "at", "by", "for", "in", "is", "it", "its", "no", "not",
    "nr", "num", "of", "or", "per", "such", "than", "that", "the", "this", "to", "use", "with",
})

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_PHONE_RE = re.compile(r"^[\d\s+()\-./]*(?:(?:x|ext\.?)\s*\d+)?$", re.IGNORECASE)
_DATE_SEP_RE = re.compile(r"[-/.\s]")
_NUM_NOISE_RE = re.compile(r"[\s,_$€£¥%]")
_BOOLEANS = frozenset({"true", "false", "yes", "no", "y", "n", "t", "f", "0", "1"})


# --- Public types: the whole pipeline depends on these and nothing else ------

@dataclass
class MappingAlternative:
    """A runner-up, surfaced so a human can accept it in one click."""

    source_column: str
    confidence: float
    rationale: str | None = None


@dataclass
class ColumnMapping:
    """The decision for one target field."""

    target_field: str
    source_column: str | None = None
    confidence: float = 0.0
    method: str = "unmapped"          # "llm" | "mock_llm" | "unmapped" | "human"
    ambiguous: bool = False
    alternatives: list[MappingAlternative] = field(default_factory=list)
    rationale: str | None = None

    @property
    def is_mapped(self) -> bool:
        return self.source_column is not None


@dataclass
class MappingResult:
    """The whole mapping decision for one upload against one schema."""

    mappings: dict[str, ColumnMapping]     # every schema field, in schema order
    unmapped_source_columns: list[str]
    provider: str                          # what ACTUALLY produced this


class ColumnMapper(Protocol):
    def map_columns(self, schema: TargetSchemaSpec, headers: list[str],
                    sample_rows: list[dict[str, str | None]]) -> MappingResult: ...


# --- Signal 1: name / description similarity --------------------------------

def _words(text: str) -> list[str]:
    """Lowercase content words; 'fullName', 'full_name', 'Full Name' all split.

    Single-letter tokens are glued to the next so punctuation-split headers
    ('E-mail', 'E Mail') normalize to the same token as 'Email'.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)
    out: list[str] = []
    for token in re.split(r"[^a-z0-9]+", spaced.lower()):
        if not token or token in _STOPWORDS:
            continue
        if out and len(out[-1]) == 1:
            out[-1] += token
        else:
            out.append(token)
    return out


@lru_cache(maxsize=512)
def _field_terms(name: str, description: str | None) -> tuple[dict[str, float], int]:
    """Weighted term set for a target field, plus its name-token count.

    The description is the richest signal available — "Work email, not personal"
    disambiguates what a field merely named `email` cannot — so its terms count
    too, just below the name's. Synonyms expand only the *name*: a name is a
    label, so a prior about labels applies; a description is prose, where the
    same prior mostly adds noise. The returned dict is cached; treat read-only.
    """
    terms: dict[str, float] = {}
    name_words = _words(name)
    for word in name_words:
        terms[word] = 1.0
        for synonym in _SYNONYMS.get(word, ()):
            terms[synonym] = max(terms.get(synonym, 0.0), SYNONYM_DISCOUNT)
    for word in _words(description or ""):
        if len(word) >= 3:
            terms.setdefault(word, DESC_TERM_WEIGHT)
    return terms, max(1, len(name_words))


def _is_abbrev(token: str, term: str) -> bool:
    """Is `token` a plausible abbreviation of `term`? 'Dept' -> department, 'CCY' -> currency.

    Spreadsheet headers abbreviate by dropping interior letters, not just by
    truncating, so a prefix test alone misses most of them. Any same-initial
    subsequence counts (which subsumes prefixes like 'Org' -> organisation);
    3+ chars are required because short tokens are a subsequence of far too
    much to be evidence.
    """
    if len(token) < 3 or len(term) <= len(token) or token[0] != term[0]:
        return False
    remaining = iter(term)
    return all(char in remaining for char in token)


def _term_weight(token: str, terms: dict[str, float]) -> float:
    """Best weight a header token earns, allowing abbreviated headers."""
    if token in terms:
        return terms[token]
    return max((ABBREV_DISCOUNT * weight for term, weight in terms.items()
                if _is_abbrev(token, term)), default=0.0)


def _name_score(header: str, target: TargetField) -> float:
    """0..1 term overlap, normalized by the smaller of the two term sets."""
    header_words = list(dict.fromkeys(_words(header)))
    if not header_words:
        return 0.0
    terms, name_len = _field_terms(target.name, target.description)
    matched = sum(_term_weight(w, terms) for w in header_words)
    return min(1.0, matched / min(len(header_words), name_len))


# --- Signal 2: content sniffing, driven by field_type -----------------------
# This is what generalizes the mapper. We cannot know what a customer's field
# means, but its declared type says what its values must look like, and that is
# checkable: a column of 100% email addresses is the email column even when it
# is called "Cell #". One validator per type, scored over the sample.

def _is_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value))


def _is_phone(value: str) -> bool:
    return 7 <= sum(c.isdigit() for c in value) <= 15 and bool(_PHONE_RE.match(value))


def _parses_as(value: str, cast: Callable[[str], Any]) -> bool:
    """Does `cast` accept the value once currency/thousands noise is stripped?"""
    cleaned = _NUM_NOISE_RE.sub("", value)
    if cleaned.startswith("(") and cleaned.endswith(")"):       # accounting negative
        cleaned = "-" + cleaned[1:-1]
    try:
        cast(cleaned)
        return True
    except ValueError:
        return False


def _is_date(value: str) -> bool:
    # Strict on purpose: dateutil reads "5" as the 5th of this month, which
    # would make every integer column look like a date column.
    if len(value) < 6 or value.replace(",", "").isdigit():
        return False
    if not (_DATE_SEP_RE.search(value) or any(c.isalpha() for c in value)):
        return False
    try:
        date_parser.parse(value)
        return True
    except (ValueError, OverflowError, TypeError):
        return False


_VALIDATORS: dict[str, Callable[[str], bool]] = {
    "email": _is_email,
    "phone": _is_phone,
    "integer": lambda v: _parses_as(v, int),
    "number": lambda v: _parses_as(v, float),
    "date": _is_date,
    "boolean": lambda v: v.strip().lower() in _BOOLEANS,
}


def _content_score(field_type: str, values: list[str]) -> float | None:
    """Fraction of sampled values fitting the type. None = no evidence either way.

    `string` is capped and never decisive: text is what a column holds when it
    holds nothing in particular, so letting free text win on content alone would
    map "Notes" to whichever text field asked first.
    """
    if not values:
        return None
    if field_type == "string":
        texty = sum(1 for v in values if not _parses_as(v, float))
        return STRING_EVIDENCE_CAP * texty / len(values)
    check = _VALIDATORS.get(field_type)
    if check is None:                          # unknown type: no opinion, name decides
        return None
    return sum(1 for v in values if check(v)) / len(values)


def _confidence(name_score: float, content_score: float | None, field_type: str) -> float:
    if content_score is None:
        score = NO_SAMPLE_DISCOUNT * name_score
    else:
        score = NAME_WEIGHT * name_score + CONTENT_WEIGHT * content_score
        if name_score >= 0.5 and content_score >= 0.7:
            score += AGREEMENT_BONUS
        if field_type != "string" and content_score >= STRONG_CONTENT:
            # Overwhelming type evidence stands on its own, whatever the header.
            score = max(score, CONTENT_ONLY_CONFIDENCE)
    return round(min(1.0, max(0.0, score)), 3)


def _evidence_note(field_type: str, content: float | None, n_values: int) -> str:
    if content is None:
        return "no sample values to corroborate"
    if field_type == "string":
        return f"{n_values} sampled values are free text (weak evidence)"
    return f"{content:.0%} of {n_values} sampled values parse as {field_type}"


def _mapped(target_field: str, column: str, confidence: float, method: str,
            alternatives: list[MappingAlternative], rationale: str | None) -> ColumnMapping:
    """Build a mapped field, deriving `ambiguous` from the winner/runner-up gap.

    Both providers share this, so "needs a human look" means the same thing
    regardless of who mapped it: unsure on its own, or barely ahead of the next
    candidate.
    """
    runner_up = alternatives[0].confidence if alternatives else None
    return ColumnMapping(
        target_field=target_field, source_column=column, confidence=confidence, method=method,
        alternatives=alternatives, rationale=rationale,
        ambiguous=confidence < LOW_CONFIDENCE
        or (runner_up is not None and confidence - runner_up <= CLOSE_RUNNER_UP),
    )


def _unmapped(target_field: str, rationale: str) -> ColumnMapping:
    return ColumnMapping(target_field=target_field, method="unmapped", rationale=rationale)


@dataclass(frozen=True)
class _Candidate:
    header: str
    index: int
    confidence: float
    name_score: float
    content_score: float | None
    n_values: int


class MockColumnMapper:
    """Deterministic offline mapper. Same output contract as the real one."""

    def map_columns(self, schema: TargetSchemaSpec, headers: list[str],
                    sample_rows: list[dict[str, str | None]]) -> MappingResult:
        values_by_header = {
            header: [v.strip() for row in sample_rows if (v := row.get(header)) and v.strip()]
            for header in headers
        }
        candidates: dict[str, list[_Candidate]] = {}
        for target in schema.fields:
            scored: list[_Candidate] = []
            for index, header in enumerate(headers):
                values = values_by_header[header]
                name = _name_score(header, target)
                content = _content_score(target.field_type, values)
                confidence = _confidence(name, content, target.field_type)
                strong = (target.field_type != "string" and content is not None
                          and content >= STRONG_CONTENT)
                # A column is a candidate only if its *header* is plausible, or
                # its values are so clearly right-shaped that the header does
                # not matter. Without this floor every text column competes for
                # every text field, and 'Notes' wins something.
                if (name >= NAME_FLOOR or strong) and confidence >= MIN_CONFIDENCE:
                    scored.append(
                        _Candidate(header, index, confidence, name, content, len(values)))
            scored.sort(key=lambda c: (-c.confidence, c.index))     # stable on ties
            candidates[target.name] = scored

        # Greedy assignment over ALL (field, column) pairs by confidence: a
        # column two fields want goes to whichever is surer of it, and no column
        # is ever bound to two fields.
        pairs = sorted(
            ((c.confidence, position, c.index, target.name, c.header)
             for position, target in enumerate(schema.fields)
             for c in candidates[target.name]),
            key=lambda p: (-p[0], p[1], p[2]),
        )
        assigned: dict[str, str] = {}
        taken: set[str] = set()
        for _, _, _, target_name, header in pairs:
            if target_name not in assigned and header not in taken:
                assigned[target_name] = header
                taken.add(header)

        mappings: dict[str, ColumnMapping] = {}
        for target in schema.fields:
            header = assigned.get(target.name)
            if header is None:
                mappings[target.name] = _unmapped(
                    target.name,
                    f"No source column resembled '{target.name}' by name, and no column's "
                    f"values looked like a {target.field_type}.")
                continue
            win = next(c for c in candidates[target.name] if c.header == header)
            others = [c for c in candidates[target.name] if c.header != header][:MAX_ALTERNATIVES]
            mappings[target.name] = _mapped(
                target.name, header, win.confidence, "mock_llm",
                [MappingAlternative(source_column=o.header, confidence=o.confidence,
                                    rationale="Runner-up on the same heuristic.") for o in others],
                f"Header similarity {win.name_score:.2f}; "
                f"{_evidence_note(target.field_type, win.content_score, win.n_values)}.")

        return MappingResult(mappings=mappings, provider="mock",
                             unmapped_source_columns=[h for h in headers if h not in taken])


# --- The real thing ---------------------------------------------------------

_SYSTEM_PROMPT = (
    "You map spreadsheet columns onto a target schema defined by the customer. Judge each "
    "column by its header AND by the sample values shown, and weigh each target field's "
    "description heavily — it is the customer's own statement of what the field means. Only "
    "ever name a column that appears verbatim in the provided header list; if nothing fits a "
    "field, return null for it rather than guessing. Never use one source column for two "
    "fields. Confidence must reflect real uncertainty: use below 0.6 whenever you would want "
    "a human to check the result."
)
_CONFIDENCE_SCHEMA = {"type": "number", "minimum": 0, "maximum": 1}
_ALTERNATIVE_SCHEMA = {
    "type": "object",
    "properties": {"source_column": {"type": "string"}, "confidence": _CONFIDENCE_SCHEMA,
                   "rationale": {"type": "string"}},
    "required": ["source_column", "confidence", "rationale"],
    "additionalProperties": False,
}


def _mapping_tool(schema: TargetSchemaSpec) -> dict[str, Any]:
    """Tool schema for *this* schema's fields — built per request, because the
    fields are the customer's, not ours.

    `strict` makes the API validate the arguments before we ever see them, which
    is why the handling below worries about *values* (a JSON schema cannot stop
    the model naming a column that does not exist) rather than about types.
    """
    entry = {
        "type": "object",
        "properties": {
            "target_field": {"type": "string", "enum": list(schema.field_names)},
            "source_column": {"type": ["string", "null"],
                              "description": "Verbatim source header, or null if none fits."},
            "confidence": _CONFIDENCE_SCHEMA,
            "rationale": {"type": "string"},
            "alternatives": {"type": "array", "items": _ALTERNATIVE_SCHEMA,
                             "description": "Up to 2 runners-up, best first."},
        },
        "required": ["target_field", "source_column", "confidence", "rationale", "alternatives"],
        "additionalProperties": False,
    }
    return {
        "name": "emit_column_mapping",
        "description": "Report the best source column for every target field.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"mappings": {"type": "array", "items": entry,
                                        "description": "Exactly one entry per target field."}},
            "required": ["mappings"],
            "additionalProperties": False,
        },
    }


def _clamp(value: Any) -> float:
    """Coerce a model-supplied confidence into 0..1; unusable means 'no idea'."""
    try:
        return round(min(1.0, max(0.0, float(value))), 3)
    except (TypeError, ValueError):
        return 0.0


class AnthropicColumnMapper:
    """Claude-backed mapper. Degrades to the mock on any failure."""

    def __init__(self, model: str | None = None) -> None:
        # Lazy import: `anthropic` is an optional dependency, so the default
        # (mock) path and the test suite must work with the package absent.
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise RuntimeError(
                "llm_provider='anthropic' requires the 'anthropic' package: pip install anthropic"
            ) from exc
        config = settings()
        api_key = config.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("llm_provider='anthropic' requires ANTHROPIC_API_KEY to be set.")
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model or config.model_mapping
        self._fallback = MockColumnMapper()

    def _build_prompt(self, schema: TargetSchemaSpec, headers: list[str],
                      sample_rows: list[dict[str, str | None]]) -> str:
        fields = "\n".join(
            f"- {f.name} ({f.field_type}, {'required' if f.required else 'optional'}): "
            f"{f.description or 'no description given'}" for f in schema.fields
        )
        # Five rows is ample shape evidence, and truncating cells keeps one wide
        # sheet from crowding out the instructions.
        rows = "\n".join(json.dumps({h: (row.get(h) or "")[:60] for h in headers})
                         for row in sample_rows[:SAMPLE_ROWS_IN_PROMPT])
        return (
            f"Target schema: {schema.name}"
            f"{f' — {schema.description}' if schema.description else ''}\n"
            f"Fields:\n{fields}\n\n"
            f"Source columns (verbatim): {json.dumps(headers)}\n\n"
            f"Sample rows:\n{rows or '(no sample rows available)'}\n\n"
            "Call emit_column_mapping with exactly one entry per target field, each with a "
            "confidence and up to two alternatives."
        )

    def map_columns(self, schema: TargetSchemaSpec, headers: list[str],
                    sample_rows: list[dict[str, str | None]]) -> MappingResult:
        try:
            # ==============================================================
            # THE REAL API CALL. One turn, no agentic loop: `tool_choice`
            # forces the schema-constrained tool, so the reply arrives as
            # structured arguments instead of prose we would have to parse.
            # ==============================================================
            response = self._client.messages.create(
                model=self._model,
                max_tokens=8000,
                system=_SYSTEM_PROMPT,
                tools=[_mapping_tool(schema)],
                tool_choice={"type": "tool", "name": "emit_column_mapping"},
                output_config={"effort": "low"},   # small, well-specified classification
                messages=[{"role": "user",
                           "content": self._build_prompt(schema, headers, sample_rows)}],
            )
            # ==============================================================
            # RESPONSE HANDLING. A safety classifier can end the turn with no
            # tool call at all, so check stop_reason before trusting content;
            # then pick the block out by name — block order is not guaranteed.
            # ==============================================================
            if response.stop_reason == "refusal":
                raise RuntimeError("model refused the mapping request")
            block = next((b for b in response.content
                          if b.type == "tool_use" and b.name == "emit_column_mapping"), None)
            if block is None:
                raise ValueError("no emit_column_mapping tool_use block in the response")
            return self._to_result(schema, block.input, headers)
        except Exception as exc:  # noqa: BLE001 - any failure degrades; none propagates
            logger.warning("Anthropic mapping failed (%s); falling back to mock mapper", exc)
            # provider stays "mock", so the API never misreports how the mapping
            # was actually produced.
            return self._fallback.map_columns(schema, headers, sample_rows)

    def _to_result(self, schema: TargetSchemaSpec, payload: Any,
                   headers: list[str]) -> MappingResult:
        """Validate the model's tool arguments into our own types."""
        entries = payload.get("mappings") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            raise ValueError("tool arguments are missing a 'mappings' list")
        by_field = {e["target_field"]: e for e in entries
                    if isinstance(e, dict) and e.get("target_field") in schema.field_names}

        mappings: dict[str, ColumnMapping] = {}
        used: set[str] = set()
        for target in schema.fields:                  # every field is always present
            entry = by_field.get(target.name) or {}
            column = entry.get("source_column")
            # Hallucination guard: only a verbatim header survives. A model
            # naming a plausible-but-absent column is the failure most likely to
            # corrupt output silently, so a column it invented, reworded, or
            # already spent on another field becomes 'unmapped' — visibly wrong
            # beats invisibly wrong.
            if column not in headers or column in used:
                mappings[target.name] = _unmapped(
                    target.name, entry.get("rationale") or "No source column matched this field.")
                continue
            used.add(column)
            alternatives = [
                MappingAlternative(source_column=a["source_column"],
                                   confidence=_clamp(a.get("confidence")),
                                   rationale=a.get("rationale"))
                for a in (entry.get("alternatives") or [])[:MAX_ALTERNATIVES]
                # Same guard for alternatives: a one-click suggestion pointing at
                # a column that does not exist is a bug in the UI's lap.
                if isinstance(a, dict) and a.get("source_column") in headers
            ]
            mappings[target.name] = _mapped(target.name, column, _clamp(entry.get("confidence")),
                                            "llm", alternatives, entry.get("rationale"))

        return MappingResult(mappings=mappings, provider="anthropic",
                             unmapped_source_columns=[h for h in headers if h not in used])


def get_mapper(provider: str | None = None) -> ColumnMapper:
    """Select a mapper: explicit arg, else configured provider, else the mock.

    Mock default: a fresh checkout runs end-to-end with no credentials.
    """
    name = (provider or settings().llm_provider or "mock").strip().lower()
    if name == "anthropic":
        return AnthropicColumnMapper()
    if name != "mock":
        raise ValueError(f"Unknown LLM provider {name!r}; expected 'mock' or 'anthropic'.")
    return MockColumnMapper()
