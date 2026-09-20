# Sheetwright User Guide

Sheetwright converts a messy spreadsheet into a clean file matching a schema you
define. You upload a CSV or Excel file, Sheetwright works out which of its
columns belong to which of your fields, shows you every decision it made, and
lets you correct anything before you export.

This guide covers everything you can do in the app.

---

## Getting started

Go to sheetwrightai.com and upload a file. There is no signup step - an
anonymous trial starts automatically on your first upload.

A trial allows **5 uploads**. Creating an account removes that limit and keeps
your history and schemas across devices. You can sign up at any point; you do
not lose work by starting as a trial.

---

## The workflow

Every conversion follows the same five steps.

### 1. Choose or define a target schema

A schema is the shape you want your data in: the list of fields, their types,
and which ones are required.

Four ready-made templates are included:

| Template | What it is for |
|---|---|
| Contacts | People you can reach. The most common import shape. |
| Products | A product or SKU catalog. |
| Transactions | Dated financial movements - ledger or statement exports. |
| Inventory | Stock on hand by location. |

You can use a template as-is, start from one and edit it, or build a schema from
scratch. Templates are available to trials and accounts alike.

Each field has a **type**, which controls how values are validated and cleaned:

- `string` - any text
- `email` - must look like an address
- `phone` - digits are extracted and reformatted; extensions are preserved
- `date` - parsed and standardised
- `integer` - whole numbers
- `number` - decimals allowed

Each field is also **required** or **optional**. Rows missing a required value
are flagged rather than silently dropped.

Write a short description for each field. It is worth the effort: the
description is what disambiguates a column called `Cell #` between a phone
number and a spreadsheet cell reference.

### 2. Upload your file

Sheetwright accepts **CSV** and **XLSX**.

Real exports are rarely clean, so the parser expects mess and handles it:

- title rows and blank lines above the actual header row
- merged cells
- ragged rows, where some rows have more or fewer columns than the header
- columns with unhelpful or duplicated names

You do not need to tidy the file first. That is the job.

### 3. Processing

Your upload is queued and processed in the background, so you can leave the page
and come back. The processing screen shows progress.

Sheetwright asks *which source column maps to which target field* once per
upload, not once per row. A 100,000-row file costs the same to map as a 100-row
one, and the result is a small mapping you can actually review.

### 4. Review every decision

This is the step that matters, and the reason to use Sheetwright rather than a
one-click converter.

For each of your target fields you will see:

- **which source column was chosen**
- **a confidence score**
- **the alternatives that were considered**, so you can see what the close calls
  were
- **a preview of real values** from that column

Two things get flagged for your attention:

- **Low confidence.** Anything below 0.60 is marked for review.
- **Ambiguity.** If the runner-up column scored nearly as well as the winner,
  the mapping is flagged even when confidence is high. A near-tie is a genuine
  coin-flip and you should decide it, not the software.

**You can override any mapping.** Point a field at a different column, or leave
it unmapped. Re-running after a change reprocesses with your correction.

Alongside the mapping you get **diagnostics** at three severities:

- `info` - a value was reformatted, for example a phone number normalised or a
  name flipped from "Surname, First" into natural order
- `warning` - something looks questionable but was kept
- `error` - a required value is missing or a value could not be validated as its
  type

Every value carries its provenance, so you can always see what the original cell
contained before any cleaning.

### 5. Export

Export the finished data as **CSV**, **XLSX**, or **JSON**.

The export reflects your reviewed mapping, including any overrides, with values
cleaned according to each field's type.

---

## Your history

The history page lists your past uploads with their status. Open any one to see
its mapping and diagnostics again, or to re-export in a different format.

Trials keep history for the life of the trial session. An account keeps it
permanently and makes it available wherever you sign in.

---

## Common questions

**Do I need an account to try it?**
No. Upload a file and an anonymous trial starts. You get 5 uploads.

**What file types can I upload?**
CSV and XLSX.

**My header row is not the first row. Does that matter?**
No. Sheetwright detects where the real header is, below title rows and blank
lines.

**A column was mapped to the wrong field. Can I fix it?**
Yes. Override it on the review screen and re-run.

**Why is a mapping flagged when its confidence looks high?**
Because the second-best candidate was nearly as good. A near-tie is flagged
regardless of the absolute score, since that is exactly the case where the
software should not decide for you.

**What happens to rows missing a required field?**
They are flagged as errors in the diagnostics rather than silently dropped, so
you can decide what to do about them.

**Can I reuse a schema?**
Yes. Schemas are saved and available for later uploads. With an account they
persist across devices.

**Can I get the data as JSON?**
Yes - CSV, XLSX, and JSON are all available at export.
