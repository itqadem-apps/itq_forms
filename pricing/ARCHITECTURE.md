# Shared Domain App Pattern — Architecture Guide

A recipe for extracting duplicated models from multiple apps into a single shared app, with proper data migration and zero downtime. Written from the `pricing` extraction in this repo but applicable to any framework or language.

---

## When to use this

You have **two or more apps** with nearly identical models (same fields, same semantics) that differ only in which parent entity they point to. You want to:

- Eliminate duplication
- Add shared behavior (e.g. Discount on top of Price)
- Query across parent types (e.g. "all prices under $10" regardless of survey vs collection)

---

## 1. Design the unified model

### The two-FK approach (recommended for ≤3 parent types)

```
┌──────────┐      ┌──────────────┐      ┌──────────────┐
│  Survey   │◄─FK──│    Price     │──FK─►│  Collection  │
└──────────┘      │              │      └──────────────┘
                  │ survey (null)│
                  │ collection   │
                  │   (null)     │
                  │ currency     │
                  │ amount_cents │
                  └──────┬───────┘
                         │
                    ┌────▼─────┐
                    │ Discount │
                    └──────────┘
```

**Rules:**
- All FK columns are **nullable**
- A **CheckConstraint** enforces exactly one FK is set
- Each FK uses the same `related_name` (e.g. `"prices"`) so existing ORM queries keep working

```python
# Django example
class Meta:
    constraints = [
        models.CheckConstraint(
            condition=(
                Q(survey__isnull=False, collection__isnull=True)
                | Q(survey__isnull=True, collection__isnull=False)
            ),
            name="price_exactly_one_parent",
        ),
    ]
```

```sql
-- Raw SQL equivalent (Postgres, MySQL, etc.)
ALTER TABLE pricing_price ADD CONSTRAINT price_exactly_one_parent
CHECK (
    (survey_id IS NOT NULL AND collection_id IS NULL)
    OR (survey_id IS NULL AND collection_id IS NOT NULL)
);
```

### When to use GenericForeignKey / polymorphic instead

- **>3 parent types** that will keep growing → ContentType / generic FK
- **Different fields per parent** → separate models are fine, don't force unification

---

## 2. Migration strategy (zero-downtime)

The key idea: **separate schema changes from state changes**. This avoids breaking the ORM while the database is mid-transition.

### Phase diagram

```
Phase 1: Claim existing table     Phase 2: Copy data     Phase 3: Rename + cleanup
─────────────────────────────     ──────────────────     ──────────────────────────

 shared app state ──► old table    copy rows from         rename table
 make old FK nullable              secondary table        drop secondary table
 add new FK column                 into unified table     add constraints
                                                          add new child models
```

### Phase 1 — Claim the existing table (no data loss)

The largest table stays in place. You re-register it under the new app's state without touching the database.

**Django:**
```python
migrations.SeparateDatabaseAndState(
    state_operations=[
        migrations.CreateModel(name="Price", fields=[...]),  # new app state
    ],
    database_operations=[
        # Alter existing table in place
        RunSQL('ALTER TABLE "old_app_price" ALTER COLUMN "survey_id" DROP NOT NULL;'),
        RunSQL('ALTER TABLE "old_app_price" ADD COLUMN "collection_id" bigint NULL ...;'),
    ],
)
```

**Rails:**
```ruby
# State is implicit in the model file — just move the model file.
# Migration only does schema changes:
class AddCollectionToPrice < ActiveRecord::Migration[7.0]
  def change
    change_column_null :prices, :survey_id, true
    add_reference :prices, :collection, null: true, foreign_key: true
  end
end
```

**Raw SQL / non-framework:**
```sql
ALTER TABLE prices ALTER COLUMN survey_id DROP NOT NULL;
ALTER TABLE prices ADD COLUMN collection_id bigint NULL REFERENCES collections(id);
CREATE INDEX idx_prices_collection_id ON prices(collection_id);
```

### Phase 2 — Copy data from the secondary table

```sql
INSERT INTO prices (currency, amount_cents, compare_at_amount_cents, survey_id, collection_id)
SELECT currency, amount_cents, compare_at_amount_cents, NULL, collection_id
FROM collection_prices;
```

Write this as a **reversible migration** — the reverse deletes rows where `survey_id IS NULL`.

### Phase 3 — Rename table, drop old, add constraints + new models

```sql
ALTER TABLE old_app_price RENAME TO pricing_price;
DROP TABLE IF EXISTS collection_prices;
ALTER TABLE pricing_price ADD CONSTRAINT price_exactly_one_parent CHECK (...);
CREATE TABLE pricing_discount (...);
```

### Phase 3b — Remove old models from source app state

**Django:** `SeparateDatabaseAndState` with `DeleteModel` in state, no DB ops.

**Rails:** Just delete the model file. The migration already moved the table.

**Other:** Remove the ORM class / entity definition from the old module.

---

## 3. App structure template

```
pricing/                          # or: shared_billing/, payments/, etc.
├── models/
│   ├── __init__.py               # re-exports Price, Discount
│   ├── price.py                  # unified model with nullable FKs
│   └── discount.py               # child model
├── types/                        # GraphQL / serializer layer
│   ├── __init__.py
│   ├── price.py                  # PriceType
│   └── discount.py               # DiscountType
├── inputs.py                     # create/update input schemas
├── schemas/
│   ├── queries/                  # read endpoints
│   └── mutations/                # write endpoints
├── migrations/
│   ├── 0001_initial.py           # claim table + alter columns
│   ├── 0002_migrate_data.py      # copy from secondary table
│   └── 0003_rename_and_add.py    # rename table, add constraint, new models
└── apps.py                       # (Django) or equivalent config
```

For **non-Django** frameworks, replace accordingly:

| Django               | Rails              | Go / generic         |
|----------------------|--------------------|----------------------|
| `models/`            | `app/models/`      | `internal/pricing/`  |
| `types/`             | `app/graphql/`     | `graph/pricing/`     |
| `inputs.py`          | `app/graphql/`     | `graph/pricing/`     |
| `migrations/`        | `db/migrate/`      | `migrations/`        |
| `apps.py`            | engine config      | `cmd/` or module     |

---

## 4. Updating consumers (existing apps)

### Imports

Old apps should **re-export** from the new shared app for backward compatibility:

```python
# old_app/models/__init__.py
from pricing.models import Price  # re-export so old imports still work
```

### Related names

If you keep the same `related_name="prices"` on the FK, **zero query changes** are needed in consuming code:

```python
# These keep working unchanged:
survey.prices.all()
collection.prices.all()
Survey.objects.filter(prices__amount_cents__gte=100)
```

### API / GraphQL types

Replace the old per-entity type with the shared type:

```python
# Before (in survey types):
@strawberry_django.type(OldPrice)
class PriceType: ...

# After:
from pricing.types import PriceType  # shared, includes discounts
```

### Event serialization

Add the new child data to event payloads:

```python
"prices": [
    {
        "currency": p.currency,
        "amount_cents": p.amount_cents,
        "discounts": [
            {"type": d.type, "value": d.value, "code": d.code}
            for d in p.discounts.all()
        ],
    }
    for p in entity.prices.all()
]
```

---

## 5. Checklist

```
[ ] Unified model with nullable FKs + CheckConstraint
[ ] Migration Phase 1: claim table, alter columns (state + DB separated)
[ ] Migration Phase 2: copy data from secondary table(s)
[ ] Migration Phase 3: rename table, drop old tables, add constraint, new models
[ ] Remove old model from source app(s) state
[ ] Register new app in framework config (INSTALLED_APPS, etc.)
[ ] Re-export model in old app's __init__ for backward compat
[ ] Update API/GraphQL types to use shared type
[ ] Update event serialization to include new child data
[ ] Update imports in tests
[ ] Add tests for:
    - Creating with each FK (survey, collection, etc.)
    - CheckConstraint violation (both null, both set)
    - New child model CRUD (Discount)
    - Existing queries still work (related_name unchanged)
[ ] All tests pass
[ ] Migrations listed correctly
```

---

## 6. Pitfalls

| Pitfall | Fix |
|---------|-----|
| **ORM thinks table doesn't exist** | Use `SeparateDatabaseAndState` — register model in state before DB changes |
| **Circular imports** (new app imports old, old imports new) | Use string references for FKs (`"surveys.Survey"`) and lazy type annotations |
| **Old FK was NOT NULL** | Must `ALTER COLUMN DROP NOT NULL` before the constraint can allow NULL |
| **Existing rows violate CheckConstraint** | Add constraint AFTER data migration, not before |
| **Table rename breaks running queries** | Deploy migration during low traffic, or use a view as alias |
| **Reverse migration leaves orphan data** | Write explicit reverse SQL — delete copied rows, recreate dropped table |
| **GraphQL type resolution fails** | Use `strawberry.lazy()` or framework equivalent for cross-module type refs |
