# Sample spreadsheets

Two deliberately awful files, in `samples/`. They stress **different** failure
modes, which is the point — a single "messy" file tends to exercise one code
path and flatter the rest.

Regenerate with `python samples/make_samples.py`.

## `sample_a_contacts.csv` — semantic mess

Header row is **row 3**:

```
Contact,E-mail Addr,Org,Cell #,Notes,Secondary Contact
```

| Exercises | Correct handling |
|---|---|
| Two junk preamble lines above the header | Scored and skipped; `preamble_skipped` note |
| Non-standard but recognisable headers | `Cell #` → `phone` from **content**, not the header name |
| `Notes` — free text, unmappable | Reported as `unmapped_source_column`, not forced into a field |
| `Secondary Contact` — names in some rows, phones in others | Genuinely ambiguous: appears as an *alternative* with a confidence, never a confident guess |
| A blank required email vs. `jane.doe@@example` | **Different** diagnostics — `missing_required_value` vs `value_needs_review` |
| Five phone formats, one with `ext. 14` | Normalised to `+1XXXXXXXXXX`; the extension is **separated**, not folded into the number |
| `NAKAMURA, Kenji` | Flipped to natural order, with a warning quoting the original |
| `Dr. Aiko Tanaka, PhD` | **Not** flipped — a credential is not a surname |
| A fully empty line mid-data | Skipped, but it still consumes its row number so `source_row` stays true to the file |
| `"Van Arsdel, Ltd."` — quoted field containing the delimiter | Parsed as one value |
| A row with both optional fields empty | Still `complete: true` |

## `sample_b_roster.xlsx` — structural mess

Header row is **row 2**:

```
Region | '  full name ' | EMAIL | Employer | Telephone | Joined | Email
```

| Exercises | Correct handling |
|---|---|
| Merged title band `A1:G1` | Unmerged; anchor value propagated |
| A merge **inside the data** (`A4:A6`, value only in `A4`) | Propagated across its range — and **not** past it. A blanket forward-fill passes the naive test and silently corrupts the next row |
| `'  full name '` untrimmed, `EMAIL` shouted | Cleaned; `original_headers` keeps the pre-rename text |
| A duplicate `Email` column | Suffixed `Email_2`, with a `duplicate_header` warning |
| Two email columns that **disagree** | `ambiguous_mapping`: *"a second column scored nearly as well (1.00 vs 1.00)"* — the case the review screen exists for |
| A blank spacer row between header and data | Skipped |
| A row with only a company | Emitted, `complete: false`, both required fields flagged |
| Phones stored as numbers (`int` and `float`) | Coerced without gaining a `.0` |
| Real `datetime` cells plus a *string* date in the same column | Both coerced to ISO |

## Why these, specifically

Every behaviour above is covered by a named test. The two files are the
fixtures for `tests/test_uploads.py`, so the claims in this table are executable
rather than aspirational.
