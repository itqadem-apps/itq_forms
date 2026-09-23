"""Test environment defaults, applied before Django is configured.

pytest-django sets Django up inside `pytest_load_initial_conftests`, which runs
BEFORE `conftest.py`'s module body — so an `os.environ` default set there lands
too late for anything `app/settings.py` reads at import time. Registering this
module as a plugin (`-p tests_env` in pytest.ini) imports it during plugin
registration, which is early enough.

`setdefault` throughout: a real environment always wins.
"""

import os

# settings.py refuses to import without a signing key, by design — there is no
# default, so that a deployed pod cannot silently run on a committed one. Tests
# sign nothing that outlives the run, so a throwaway value is correct here.
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-not-a-real-key")

# conftest.py pins the test database to in-memory sqlite; these are the same
# values, set early enough for settings.py to read them.
os.environ.setdefault("DATABASE_ENGINE", "django.db.backends.sqlite3")
os.environ.setdefault("DATABASE_NAME", ":memory:")
