"""Declarative legacy -> itq_forms column mapping.

The mapping is *total*: every column of every in-scope legacy table resolves to
exactly one disposition. `assert_total()` checks that claim against the live
legacy catalog and refuses to run if a column has appeared that nobody has
ruled on. That gate is the whole point of this module -- the previous importer
had an `ignored_fields` set with no such check, so `content_type`/`object_id`
were silently dropped along with 119 collection links.

Reviewed mapping: https://claude.ai/code/artifact/c8b25761-b0be-4f3a-8469-cc27dcd4c223
"""

from .spec import (  # noqa: F401
    TABLES,
    Column,
    Drop,
    Rename,
    Same,
    Table,
    Translate,
    assert_total,
)
