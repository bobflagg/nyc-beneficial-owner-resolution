"""CONNECTED_BY_SPLINK — feed Splink's owner resolution into WoW's portfolio graph.

Mechanism B (see CLAUDE.md "Splink as a de-dup edge"). Splink resolves raw HPD owner
contacts into precision-first entities; this emits a high-weight edge between every pair
of ``landlords_with_connections`` nodes that resolve to the *same* owner. The pipeline's
WCC+Louvain then merges the fragments WoW's name/address matching split — Croman's typo'd
offices collapse from 6 portfolios into 1 — WITHOUT changing anything WoW already links:
edges only ADD, so connected components can only *merge*, never split. An existing
portfolio (e.g. an agent-linked shell operation) is therefore safe by construction.

This module is Neo4j-free: it runs off Postgres + Splink and returns
``(src_nodeid, dst_nodeid, weight)`` so ``pipeline.py`` can MATCH the ``Actor`` nodes by
``ACT-LL-<nodeid>`` and MERGE the relationships (mirroring the name/address edge load).

Node mapping is EXACT, not fuzzy. A Splink contact and an lwc node both carry the same
``(owner name, bbl)`` from the same HPD registration, so an explode-and-join on
``(name, bbl)`` maps each lwc node to its Splink entity — 99.9% of lwc nodes covered in
the production run, with zero edges linking different surnames (the name-anchored
resolution + first-name/common-name vetoes guarantee that).

Runs against whatever ``PGDATABASE`` points at; in production that is the ``wow`` DB, so
Splink reads ``wow.hpd_contacts`` and the join reads ``wow.landlords_with_connections``.
"""
from __future__ import annotations

import re
from itertools import combinations

import pandas as pd

from nlr import Resolution, resolve_entities
from bor import aggregator_officer_audit as aoa
from bor._edges import SPLINK_WEIGHT, STAR_ABOVE   # uniform edge weight + star threshold (shared kernel)

# Clustering threshold. The stratified slice (below) is dense in same-name pairs, so the
# model scores same-name/same-address pairs confidently; 0.999 restores gold precision to
# 0.996 (0 cross-surname). Calibrated against the 105-record gold set + an independent ACRIS
# multi-parcel-deed check (~83% co-ownership agreement, population-wide). See notes below.
DEFAULT_THRESHOLD = 0.999

_norm = lambda s: re.sub(r"\s+", " ", s).strip().upper() if isinstance(s, str) else s


def resolve(conn, threshold: float = DEFAULT_THRESHOLD, *, capture: bool = False) -> Resolution:
    """The full-population nlr resolution, with the F12 exclusion.

    One pipeline, in nlr (:func:`nlr.resolve_entities`): name-anchored blocking plus the first-name
    and common-name vetoes, trained on a stratified slice, then a corp-co-owner feedback pass that
    bridges same-owner offices sharing a private corp (Croman via Centennial, Rashad via The
    Andrews Organization). bor adds one thing: it drops curated mortgage-servicer / REO signers
    (out-of-state officers whose buildings are servicer-owned: Fannie Mae, Selene, Shellpoint,
    Reverse Mortgage Solutions; e.g. ERIC MOORE) from the resolution input, so their buildings
    resolve by owner-of-record (registered-llc / deed), NOT by the shared signer name. nlr applies
    the exclusion before clustering AND the feedback loop, so it is feedback-proof (a clusterer-only
    veto is not: feedback_merge re-merges past it). See aggregator_officer_audit (curated
    allowlist gated by the servicer-corp rule) / phase-2 findings F12.

    ``capture=True`` also records the decisions behind the clusters (``Resolution.trace``)."""
    return resolve_entities(conn, threshold=threshold, capture=capture,
                            exclude_names=aoa.excluded_officer_names(conn))


def _resolve(conn, threshold: float):
    """``(identities, clusters)`` of :func:`resolve`; the shape the edge builders consume."""
    res = resolve(conn, threshold)
    return res.identities, res.clusters


def node_cluster_votes(conn, full: pd.DataFrame, clusters: pd.DataFrame) -> pd.DataFrame:
    """The (name, bbl) join between lwc nodes and resolved identities, one row per match.

    Returns ``[nodeid, name, bbl, unique_id, cluster_id]``. A node can match several identities
    (spelling variants of one address) and, rarely, identities in different clusters."""
    sp = clusters[["unique_id", "cluster_id"]].merge(
        full[["unique_id", "name_full", "bbls"]], on="unique_id")
    sp = sp.explode("bbls").rename(columns={"bbls": "bbl", "name_full": "name"})
    sp["name"] = sp["name"].map(_norm)
    sp = sp[["unique_id", "cluster_id", "name", "bbl"]].dropna()

    lwc = pd.read_sql(
        "SELECT nodeid, name, bbls::text[] AS bbls FROM landlords_with_connections", conn)
    ln = lwc.explode("bbls").rename(columns={"bbls": "bbl"})[["nodeid", "name", "bbl"]].copy()
    ln["name"] = ln["name"].map(_norm)

    return ln.merge(sp, on=["name", "bbl"], how="inner")


def select_cluster(votes: pd.DataFrame) -> pd.DataFrame:
    """One cluster per node: the plurality over its (name, bbl) matches. Returns
    ``[nodeid, cluster_id]``.

    A tie goes to the smallest cluster label (``Series.mode`` sorts ascending). That is
    deterministic for one fit but carries no meaning, and labels change between fits."""
    return (votes.groupby("nodeid")["cluster_id"]
                 .agg(lambda s: s.mode().iloc[0]).rename("cluster_id").reset_index())


def node_clusters(conn, *, threshold: float = DEFAULT_THRESHOLD) -> pd.DataFrame:
    """Map each ``landlords_with_connections`` node to its Splink entity.

    Returns ``[nodeid, cluster_id]``. A node whose buildings straddle two entities
    (rare) takes the plurality entity of its bbls."""
    full, clusters = _resolve(conn, threshold)
    return select_cluster(node_cluster_votes(conn, full, clusters))


def splink_edges(conn, *, threshold: float = DEFAULT_THRESHOLD, weight: float = SPLINK_WEIGHT,
                 star_above: int = STAR_ABOVE, node_cluster_frame: pd.DataFrame | None = None) -> pd.DataFrame:
    """CONNECTED_BY_SPLINK edges as ``[src, dst, weight]`` over lwc nodeids.

    One clique per resolved entity of >=2 nodes (so the group stays dense under Louvain);
    entities larger than ``star_above`` fall back to a hub-and-spoke star to bound edges.

    Pass ``node_cluster_frame`` (``[nodeid, cluster_id]``, only the partition matters) to build the edges
    from a resolution already in hand instead of fitting Splink again; a release does this so that
    every layer comes from one fit.
    """
    nc = node_cluster_frame if node_cluster_frame is not None else node_clusters(conn, threshold=threshold)
    rows: list[tuple[int, int]] = []
    for _, g in nc.groupby("cluster_id"):
        ids = sorted(g["nodeid"].tolist())
        if len(ids) < 2:
            continue
        if len(ids) <= star_above:
            rows.extend(combinations(ids, 2))
        else:
            rows.extend((ids[0], d) for d in ids[1:])
    edges = pd.DataFrame(rows, columns=["src", "dst"])
    edges["weight"] = float(weight)
    return edges


if __name__ == "__main__":  # quick read-only sanity run (PGDATABASE must point at wow)
    import warnings; warnings.filterwarnings("ignore")
    import logging; logging.getLogger("splink").setLevel(logging.ERROR)
    from bor.db import pg_conn
    conn = pg_conn()
    E = splink_edges(conn)
    conn.close()
    n = pd.unique(E[["src", "dst"]].values.ravel())
    print(f"CONNECTED_BY_SPLINK: {len(E):,} edges over {len(n):,} nodes")
