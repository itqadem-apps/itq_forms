---
name: 'forms'
type: architecture-spine
purpose: build-substrate
altitude: initiative
paradigm: 'a Django project, unlike its ports-and-adapters siblings'
scope: 'invariants binding the forms service'
status: draft
created: '2026-08-28'
updated: '2026-08-28'
binds: []
sources: []
companions: []
---

# Architecture Spine — forms

## Design Paradigm

A Django project, and the exception in a backend otherwise built ports-and-adapters. It is organised as Django apps — `accounts/`, `assessment_exports/`, `classifications/`, `external_references/` — around a conventional `app/` settings package with a GraphQL surface (`schema_common.py`), its own permission catalogue and database routers. A reader arriving from any sibling service will find none of `domain/ app/ infra/ interface/` here, and that difference is structural rather than an oversight.

## Inherited Invariants

These are the estate's, listed by their original ids and **not** re-keyed here — a second key
for one decision is the collision the namespace grammar exists to prevent. Where anything below
disagrees with one of these, the inherited decision wins and the disagreement is a conflict to
surface, not a local override.

- `estate:AD-1` — the knowledge base is a routing aid, never the authority
- `estate:AD-2` — a decision lives in the repo it binds
- `estate:AD-3` — every citation is namespaced
- `estate:AD-4` — board automation never moves a card between lists
- `estate:AD-5` — human requests enter through a separate board, and only through triage
- `estate:AD-6` — courses is the system of record for live cohorts
- `estate:AD-7` — one NATS subject grammar: `<service>.<aggregate_type>`, event variant in the payload
- `estate:AD-8` — two ACL database roles: SELECT-only at runtime, write-capable only at deploy

## Invariants & Rules

None yet. This spine was scaffolded on 2026-08-28 as a container only: nothing has been ruled for
the `forms` namespace, and an invariant invented at scaffold time is a guess wearing a
citation. Numbering starts at one when the first decision is actually made, and is never reused
or renumbered after that.

## Deferred

Not yet enumerated. The gaps this repo knows it owes are recorded here as they are noticed —
a named gap is worth more than silence, because it stops the next reader concluding the
question was never asked.
