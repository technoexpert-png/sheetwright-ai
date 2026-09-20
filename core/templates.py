"""Starter target schemas.

Templates are *copied* into an org at signup rather than referenced globally.
A customer editing "Contacts" must not change it for anyone else, and a shared
row would make that the default behavior.

Field descriptions carry real weight: they are the main signal the column
mapper reasons over. "Work email, not personal" resolves ambiguity that a field
merely named `email` cannot, so each one is written for the model to read.
"""

from __future__ import annotations

from typing import TypedDict


class FieldSpec(TypedDict):
    name: str
    field_type: str
    required: bool
    description: str


class TemplateSpec(TypedDict):
    name: str
    description: str
    fields: list[FieldSpec]


SCHEMA_TEMPLATES: dict[str, TemplateSpec] = {
    "contacts": {
        "name": "Contacts",
        "description": "People you can reach — the most common import shape.",
        "fields": [
            {"name": "full_name", "field_type": "string", "required": True,
             "description": "Person's full name in natural order (first last), not surname-first."},
            {"name": "email", "field_type": "email", "required": True,
             "description": "Primary email address for this person."},
            {"name": "company", "field_type": "string", "required": False,
             "description": "Employer or organization name, not a job title."},
            {"name": "phone", "field_type": "phone", "required": False,
             "description": "Contact phone number in any format."},
        ],
    },
    "products": {
        "name": "Products",
        "description": "A product or SKU catalog.",
        "fields": [
            {"name": "sku", "field_type": "string", "required": True,
             "description": "Unique product or stock-keeping identifier."},
            {"name": "title", "field_type": "string", "required": True,
             "description": "Customer-facing product name."},
            {"name": "price", "field_type": "number", "required": False,
             "description": "Unit price as a number, currency symbols stripped."},
            {"name": "currency", "field_type": "string", "required": False,
             "description": "Three-letter currency code such as USD or EUR."},
            {"name": "category", "field_type": "string", "required": False,
             "description": "Product category or department."},
        ],
    },
    "transactions": {
        "name": "Transactions",
        "description": "Dated financial movements — ledger or statement exports.",
        "fields": [
            {"name": "transacted_on", "field_type": "date", "required": True,
             "description": "Date the transaction occurred, not the date it was recorded."},
            {"name": "description", "field_type": "string", "required": True,
             "description": "Memo, narrative, or payee text."},
            {"name": "amount", "field_type": "number", "required": True,
             "description": "Signed amount; negative for debits or money out."},
            {"name": "reference", "field_type": "string", "required": False,
             "description": "Cheque number, invoice id, or other reference."},
        ],
    },
    "inventory": {
        "name": "Inventory",
        "description": "Stock on hand by location.",
        "fields": [
            {"name": "sku", "field_type": "string", "required": True,
             "description": "Stock-keeping identifier."},
            {"name": "quantity", "field_type": "integer", "required": True,
             "description": "Whole-number units on hand."},
            {"name": "location", "field_type": "string", "required": False,
             "description": "Warehouse, store, or bin identifier."},
            {"name": "counted_on", "field_type": "date", "required": False,
             "description": "Date the count was taken."},
        ],
    },
}


def template_names() -> list[str]:
    return sorted(SCHEMA_TEMPLATES)


def seed_org_templates(scope) -> list:
    """Copy every template into a new org.

    Called once at signup. Seeding all four rather than asking the customer to
    choose means the product is immediately usable, and an unused schema costs
    nothing but a row.
    """
    from db.models import FieldType, SchemaField, TargetSchema

    created = []
    for key, spec in SCHEMA_TEMPLATES.items():
        schema = scope.create(
            TargetSchema,
            name=spec["name"],
            description=spec["description"],
            from_template=key,
        )
        schema.fields = [
            SchemaField(
                name=f["name"],
                field_type=FieldType(f["field_type"]),
                required=f["required"],
                description=f["description"],
                position=i,
            )
            for i, f in enumerate(spec["fields"])
        ]
        created.append(schema)
    return created
