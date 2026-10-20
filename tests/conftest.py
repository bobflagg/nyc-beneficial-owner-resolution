"""Shared fixtures. Integration fixtures need a Postgres (the JustFix `justfixwow` dump with lwc
built); without `PGDATABASE` set they skip, so a plain `pytest` runs the unit tests offline.

The resolutions are expensive (~4 min of Splink each), so they are session-scoped and reused
across the integration tests.
"""
import os

import pytest


@pytest.fixture(scope="session")
def pg():
    if not os.environ.get("PGDATABASE"):
        pytest.skip("no PG* env — integration tests need the justfixwow Postgres (see docs/data.md)")
    from bor.db import pg_conn
    conn = pg_conn()
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def resolved(pg):
    from bor.splink_bridge import DEFAULT_THRESHOLD, _resolve
    return _resolve(pg, DEFAULT_THRESHOLD)


@pytest.fixture(scope="session")
def owner_groups(pg):
    from bor.owner_groups import resolve_owner_groups
    return resolve_owner_groups(pg)


@pytest.fixture(scope="session")
def operational_networks(pg):
    from bor.operational_network import resolve_operational_networks
    return resolve_operational_networks(pg)
