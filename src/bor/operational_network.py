"""bor/operational_network.py — the operational network (v1.1), off-graph.

*What a building operates through* — the shared-infrastructure clustering that is WoW's own
notion of a "portfolio," here rebuilt off Neo4j. It is WCC(+Louvain) over three edge types:

  * NAME    — WoW's fuzzy name self-join (precomputed in lwc.name_match_info), weight ×1.5
  * ADDRESS — WoW's business-address self-join (lwc.bizaddr_match_info), weight ×1.0, with
              aggregator megaoffices (>25 landlords) masked out
  * SPLINK  — the resolved-owner cliques (model ∪ curated ∪ registered-LLC), weight 100

Mirrors WatchlineNYC's Portfolio layer (portfolio/algorithms.py) exactly in structure:

  1. WCC over name ∪ address ∪ splink (unweighted connectivity) — pure union-find, EXACT.
  2. For each component whose BBL-sum exceeds MAX_SIZE (300), recursively split with weighted
     Louvain until each piece fits. This is the ONE non-exact step: WatchlineNYC runs GDS's
     seedless, default-granularity Louvain, which a Python Louvain (igraph) cannot byte-match —
     and which GDS itself does not reproduce run-to-run. It fires only on a tail of a few dozen
     oversized components (large operators like Kadden ~496 BBLs); the vast majority of portfolios
     are ≤300 BBLs, pure WCC, and reproduce exactly. See docs/parity.md.

Off-graph: everything is Postgres (the name/address edges are already materialized as JSON in
`landlords_with_connections`) plus the splink edges this package already builds. No Neo4j.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from bor.curated_owners import curated_edges
from bor.llc_edges import llc_edges
from bor.splink_bridge import DEFAULT_THRESHOLD, splink_edges

# Edge weights (matter only inside Louvain; WCC ignores them). From portfolio/pipeline.py:113-123.
NAME_WEIGHT_MULTIPLIER = 1.5
ADDRESS_WEIGHT_MULTIPLIER = 1.0
MAX_ADDR_DEGREE = 25       # a normalized business address on more distinct landlords is an aggregator
MAX_SIZE = 300             # max buildings (BBLs) per portfolio before Louvain splitting

# Address normalizer, forked verbatim from aggregator_audit._norm (strip a trailing ", CITY NY",
# uppercase, collapse whitespace) so the aggregator mask groups the same addresses the KG masks.
_SUFFIX = re.compile(r",\s*[A-Z ]+\s+NY\s*$")


def _norm_bizaddr(addr) -> str:
    if not isinstance(addr, str):
        return ""
    return re.sub(r"\s+", " ", _SUFFIX.sub("", addr.upper().strip())).strip()


_LWC_EDGE_SQL = "SELECT nodeid, name_match_info, bizaddr_match_info FROM landlords_with_connections"
_BBL_COUNT_SQL = "SELECT nodeid, coalesce(array_length(bbls, 1), 0) FROM landlords_with_connections"
_NODE_BBL_SQL = "SELECT nodeid, bbls::text[] AS bbls FROM landlords_with_connections"


def _aggregator_nodes(conn) -> set[int]:
    """lwc nodeids whose normalized business address is shared by > MAX_ADDR_DEGREE distinct
    landlords (a registered-agent / management megaoffice). Address edges touching one are masked."""
    with conn.cursor() as cur:
        cur.execute("SELECT bizaddr FROM landlords_with_connections WHERE bizaddr IS NOT NULL")
        counts = Counter(_norm_bizaddr(r[0]) for r in cur)   # one lwc row = one distinct landlord
    aggregators = {a for a, n in counts.items() if a and n > MAX_ADDR_DEGREE}
    with conn.cursor() as cur:
        cur.execute("SELECT nodeid, bizaddr FROM landlords_with_connections WHERE bizaddr IS NOT NULL")
        return {r[0] for r in cur if _norm_bizaddr(r[1]) in aggregators}


def _name_address_edges(conn, agg_nodes: set[int]) -> list[tuple[int, int, float]]:
    """Parse the precomputed NAME and ADDRESS edges from lwc's JSON columns (mirrors
    pipeline._edge_batches): weight the name/address links, and drop address edges where either
    endpoint is an aggregator node."""
    edges: list[tuple[int, int, float]] = []
    with conn.cursor(name="opnet_edges") as cur:
        cur.itersize = 5000
        cur.execute(_LWC_EDGE_SQL)
        for nodeid, nmi, bmi in cur:
            for m in (nmi or []):
                edges.append((nodeid, m["nodeid"], float(m["weight"]) * NAME_WEIGHT_MULTIPLIER))
            if nodeid in agg_nodes:
                continue                                     # aggregator src: skip all its address edges
            for m in (bmi or []):
                if m["nodeid"] in agg_nodes:
                    continue                                 # aggregator dst: skip too
                edges.append((nodeid, m["nodeid"], float(m["weight"]) * ADDRESS_WEIGHT_MULTIPLIER))
    return edges


def _splink_edges(conn, *, threshold: float) -> list[tuple[int, int, float]]:
    """Resolved-owner edges (model ∪ curated ∪ registered-LLC) as weighted nodeid pairs."""
    out: list[tuple[int, int, float]] = []
    for f in (splink_edges(conn, threshold=threshold), curated_edges(conn), llc_edges(conn)):
        for s, d, w in zip(f["src"], f["dst"], f["weight"]):
            out.append((int(s), int(d), float(w)))
    return out


def _collapse(edges: list[tuple[int, int, float]]) -> dict[tuple[int, int], float]:
    """Sum weights of parallel edges (a NAME + ADDRESS + SPLINK link between one pair) into one
    weighted edge, keyed by the ordered pair."""
    w: dict[tuple[int, int], float] = defaultdict(float)
    for a, b, wt in edges:
        if a == b:
            continue
        w[(a, b) if a < b else (b, a)] += wt
    return w


def _components(pairs) -> list[list[int]]:
    """Weakly-connected components (union-find) over unordered nodeid pairs."""
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        r = x
        while parent[r] != r:
            r = parent[r]
        while parent[x] != r:
            parent[x], x = r, parent[x]
        return r

    nodes: set[int] = set()
    for a, b in pairs:
        nodes.add(a); nodes.add(b)
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    comp: dict[int, list[int]] = defaultdict(list)
    for n in nodes:
        comp[find(n)].append(n)
    return list(comp.values())


def _louvain_communities(node_ids: list[int], wedges: dict[tuple[int, int], float]) -> list[list[int]]:
    """One weighted Louvain pass over the induced subgraph, via igraph.community_multilevel."""
    try:
        import igraph
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "the operational-network layer needs igraph — `uv sync` (it is a core dependency)") from e
    nid = sorted(node_ids)
    idx = {n: i for i, n in enumerate(nid)}
    members = set(node_ids)
    ig_edges, weights = [], []
    for (a, b), wt in wedges.items():
        if a in members and b in members:
            ig_edges.append((idx[a], idx[b])); weights.append(wt)
    g = igraph.Graph(n=len(nid), edges=ig_edges)
    part = g.community_multilevel(weights=weights or None)
    comms: dict[int, list[int]] = defaultdict(list)
    for i, c in enumerate(part.membership):
        comms[c].append(nid[i])
    return list(comms.values())


@dataclass
class OperationalNetwork:
    """One operational-network portfolio. ``split`` records how it was cut out: ``wcc`` (a whole
    connected component that fit under the cap — exact) or ``louvain`` (a sub-community of an
    oversized component — approximate, GDS-Louvain not byte-reproducible)."""
    operational_network_id: str          # ON-<min nodeid> — deterministic given the partition
    members: list[int]         # lwc nodeids
    bbls: list[str]            # union of members' bbls
    split: str                 # "wcc" | "louvain"

    @property
    def building_count(self) -> int:
        return len(self.bbls)


def resolve_operational_networks(conn, *, threshold: float = DEFAULT_THRESHOLD,
                                 max_size: int = MAX_SIZE) -> list[OperationalNetwork]:
    """Resolve the operational-network layer off-graph. WCC over name ∪ address ∪ splink, then
    weighted Louvain on components whose BBL-sum exceeds ``max_size``. KG-free."""
    agg = _aggregator_nodes(conn)
    edges = _name_address_edges(conn, agg) + _splink_edges(conn, threshold=threshold)
    wedges = _collapse(edges)
    pairs = list(wedges)

    with conn.cursor() as cur:
        cur.execute(_BBL_COUNT_SQL)
        bbl_counts = {r[0]: int(r[1]) for r in cur}

    def size(ids) -> int:
        return sum(bbl_counts.get(n, 0) for n in ids)

    # WCC, then recursive Louvain on oversized components (mirrors algorithms.iter_portfolios/_split)
    finals: list[tuple[str, list[int]]] = []   # (split_kind, members)

    def split(ids: list[int], kind: str) -> None:
        if size(ids) <= max_size:
            finals.append((kind, ids)); return
        comms = _louvain_communities(ids, wedges)
        if len(comms) <= 1 or max(size(c) for c in comms) == size(ids):
            finals.append((kind, ids)); return       # Louvain found no meaningful split — emit as-is
        for c in comms:
            split(c, "louvain")

    for comp in _components(pairs):
        split(comp, "wcc")

    # attach bbls and mint deterministic ids
    node_bbls: dict[int, list[str]] = {}
    want = {n for _, ids in finals for n in ids}
    with conn.cursor() as cur:
        cur.execute(_NODE_BBL_SQL)
        for nodeid, bbls in cur:
            if nodeid in want:
                node_bbls[nodeid] = [str(b).strip() for b in (bbls or []) if b]

    out: list[OperationalNetwork] = []
    for kind, ids in finals:
        bbls = sorted({b for n in ids for b in node_bbls.get(n, [])})
        out.append(OperationalNetwork(
            operational_network_id=f"ON-{min(ids)}", members=sorted(ids), bbls=bbls, split=kind))
    return sorted(out, key=lambda p: p.operational_network_id)


def bbl_assignments(networks: list[OperationalNetwork]) -> dict[str, str]:
    """``{bbl: operational_network_id}`` for parity/comparison."""
    return {b: n.operational_network_id for n in networks for b in n.bbls}
