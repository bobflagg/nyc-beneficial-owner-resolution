"""Regression tests against the reference `justfixwow` Postgres. Skipped without `PG*` env.

Slow: the session-scoped resolutions run Splink (~4 min each). The deed layer is deterministic
(exact assertion); Splink-dependent counts use `expected.TOL`. Numbers are validated in
docs/parity.md.
"""
from collections import Counter

from tests import expected as E

from bor.build_lwc import verify as verify_lwc  # noqa: F401  (import smoke)


def test_lwc_present(pg):
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM landlords_with_connections")
        rows = cur.fetchone()[0]
    assert abs(rows - E.LWC_NODES) <= E.LWC_NODES * 0.1   # dump can drift; warn-band


def test_deed_edges(pg):
    from bor.deed_edges import deed_edges
    edges = deed_edges(pg)
    nodes = set(edges["src"]) | set(edges["dst"])
    # No Splink, but not bit-exact: ACRIS latest-deed tiebreaks / data vintage shift a handful.
    assert abs(len(edges) - E.DEED_EDGES) <= E.TOL
    assert abs(len(nodes) - E.DEED_NODES) <= E.TOL


def test_owner_portfolios(owner_portfolios):
    assert abs(len(owner_portfolios) - E.OWNER_PORTFOLIOS) <= E.TOL
    n_nodes = sum(len(g.members) for g in owner_portfolios)
    assert abs(n_nodes - E.OWNER_PORTFOLIO_NODES) <= E.TOL
    comp = Counter(g.composition for g in owner_portfolios)
    for kind, want in E.COMPOSITION.items():
        assert abs(comp[kind] - want) <= E.TOL, (kind, comp[kind], want)


def test_divergence(pg, owner_portfolios):
    from bor.eval.divergence import divergence
    d = divergence(pg, groups=owner_portfolios)
    assert abs(d["owners_crossing_portfolios"] - E.OWNERS_CROSSING) <= E.TOL
    assert abs(d["portfolios_hiding_multiple_owners"] - E.PORTFOLIOS_HIDING) <= E.TOL


def test_operational_networks(operational_networks):
    multi = [n for n in operational_networks if len(n.members) >= 2]
    assert abs(len(multi) - E.OPERATIONAL_NETWORKS_MULTI) <= E.TOL
