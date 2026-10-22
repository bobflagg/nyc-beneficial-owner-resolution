"""Shared fixtures. Integration fixtures need a Postgres (the JustFix `justfixwow` dump with lwc
built); without `PGDATABASE` set they skip, so a plain `pytest` runs the unit tests offline.
Importing nlr loads a `.env` found above its install, so with nlr installed in this checkout's `.venv`
a `.env` here sets `PGDATABASE` and runs them. `make test-offline` (an empty `PGDATABASE`) skips them.

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
    from bor.splink_bridge import DEFAULT_THRESHOLD, resolve
    return resolve(pg, DEFAULT_THRESHOLD, capture=True)


@pytest.fixture(scope="session")
def release_build(pg, resolved, tmp_path_factory):
    """One full release built from the reference dump (~8 min), shared by the tests that read it."""
    from datetime import date

    from bor.release import build_release
    out = tmp_path_factory.mktemp("release")
    result = build_release(pg, out, snapshot_id="justfixwow-2026-05-29", as_of=date(2026, 10, 21), resolution=resolved)
    return out, result


@pytest.fixture(scope="session")
def node_cluster_frame(pg):
    """One Splink fit for the layer fixtures below, shared as a release shares it (the fit is ~4 min)."""
    from bor.splink_bridge import node_clusters
    return node_clusters(pg)


@pytest.fixture(scope="session")
def owner_portfolios(pg, node_cluster_frame):
    from bor.owner_portfolios import resolve_owner_portfolios
    return resolve_owner_portfolios(pg, node_cluster_frame=node_cluster_frame)


@pytest.fixture(scope="session")
def operational_networks(pg, node_cluster_frame):
    from bor.operational_network import resolve_operational_networks
    return resolve_operational_networks(pg, node_cluster_frame=node_cluster_frame)
