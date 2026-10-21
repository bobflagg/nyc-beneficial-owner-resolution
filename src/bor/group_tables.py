"""Owner Portfolios, lots and witness paths for the release (W4; docs/w4-design.md).

The group partition comes from :mod:`bor.owner_portfolios`. This module explains it: for each group
it builds a **representative path**, a spanning tree over the group's nodes in which every step cites
the evidence that joined two nodes (an identity cluster, a curated owner, a registered-LLC entity, or
a deed). The path is a tree: connected, acyclic, one step fewer than the group has members.

Every kind of link ties a *set* of nodes together, so a step cites the set, and the tree is built by
a union-find over the sets in a fixed order that prefers the least questionable evidence. A weak
stage therefore appears only when the group cannot be connected without it.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import pandas as pd

LAYER = "owner_portfolio"

# Processing order of link sets. Earlier tiers are preferred, so a path uses a later (weaker) kind of
# evidence only where the earlier ones leave the group unconnected.
TIER_BASE, TIER_CURATED, TIER_LLC, TIER_DEED_HELD, TIER_FEEDBACK, TIER_DEED_GUARD = range(6)

GROUP_COLUMNS = ["layer", "group_id", "assertion_key", "composition", "split", "lot_count", "total_lot_count"]
MEMBER_COLUMNS = ["layer", "group_id", "node_id", "assertion_key"]
BBL_COLUMNS = ["layer", "group_id", "bbl", "rental"]
WITNESS_COLUMNS = ["layer", "group_id", "step", "node_a", "node_b", "stage", "basis_type", "basis_id",
                   "assertion_key"]
LINK_SET_COLUMNS = ["set_id", "stage", "rule", "rule_version", "size"]
LINK_SET_MEMBER_COLUMNS = ["set_id", "node_id", "source_bbl"]


@dataclass(frozen=True)
class LinkSet:
    """A set of nodes tied together by one piece of evidence. ``nodes[0]`` is the centre the tree
    hangs the others from, so every step is a pair from the set."""
    tier: int
    stage: str
    basis_type: str
    basis_id: str
    nodes: tuple[int, ...]

    @property
    def order(self):
        return (self.tier, self.basis_id, self.nodes)


# ---- link sets from each source -----------------------------------------------------------------

def cluster_link_sets(node_cluster: pd.DataFrame, matches: pd.DataFrame, identity_clusters: pd.DataFrame
                      ) -> list[LinkSet]:
    """The identity-cluster sets. Within a final cluster C: one set per base cluster (nodes whose
    matched identities share it) at the base tier, then C as a whole at the feedback tier, which is
    what joins nodes whose base clusters differ.

    ``node_cluster`` has ``node_id, cluster_id``; ``matches`` ``node_id, identity_id``;
    ``identity_clusters`` ``identity_id, cluster_id, base_cluster_id``."""
    ic = identity_clusters.set_index("identity_id")
    m = matches[["node_id", "identity_id"]].drop_duplicates().join(ic, on="identity_id")
    m = m.merge(node_cluster.rename(columns={"cluster_id": "assigned"}), on="node_id")
    m = m[m["cluster_id"] == m["assigned"]]                     # identities in the node's assigned cluster
    out: list[LinkSet] = []
    for cluster, nodes in node_cluster.groupby("cluster_id")["node_id"]:
        nodes = sorted(int(n) for n in nodes)
        if len(nodes) < 2:
            continue
        mc = m[m["assigned"] == cluster]
        by_base = defaultdict(set)
        for node, base in zip(mc["node_id"], mc["base_cluster_id"]):
            by_base[base].add(int(node))
        for base in sorted(by_base):
            ns = sorted(by_base[base])
            if len(ns) >= 2:
                out.append(LinkSet(TIER_BASE, "identity.splink_base", "identity_cluster", cluster, tuple(ns)))
        out.append(LinkSet(TIER_FEEDBACK, "identity.splink_feedback", "identity_cluster", cluster, tuple(nodes)))
    return out


def deed_link_sets(items: pd.DataFrame, members: pd.DataFrame) -> list[LinkSet]:
    """Each deed that links nodes. Nodes that hold a parcel directly under the joint deed form a
    held-since set; the nodes that are in the deed only through a transferred-onward parcel (they
    depend on the linked-successor guard) join in a later, weaker set. Hub nodes are left out, as in
    the deed edges."""
    out: list[LinkSet] = []
    live = members[members["excluded_reason"].isna()]
    for eid, g in live.groupby("evidence_id"):
        held = sorted({int(n) for n in g.loc[g["role"] == "held_under_joint_deed", "node_id"]})
        every = sorted({int(n) for n in g["node_id"]})
        if len(held) >= 2:
            out.append(LinkSet(TIER_DEED_HELD, "deed.held_since", "evidence_item", eid, tuple(held)))
        if len(every) > len(held) and len(every) >= 2:
            centre = held[0] if held else every[0]
            rest = [n for n in every if n != centre]
            out.append(LinkSet(TIER_DEED_GUARD, "deed.linked_successor", "evidence_item", eid,
                               tuple([centre] + rest)))
    return out


@dataclass
class LinkSets:
    """Curated owners and registered-LLC entities as citable sets, with opaque ids."""
    sets: pd.DataFrame
    members: pd.DataFrame
    link_sets: list[LinkSet] = field(default_factory=list)


def named_link_sets(curated: dict, llc_sources: dict, curated_version: str, llc_version: str) -> LinkSets:
    """``curated``: owner key -> nodes. ``llc_sources``: entity -> {node: [source BBLs]} (the PLUTO
    lots the entity owns that put the node in the set). Keys are used to group only; the exported ids
    are ``CG0000001`` / ``LG0000001``, numbered by each set's smallest node."""
    sets_rows, mem_rows, ls = [], [], []
    for prefix, stage, rule, version, tier, groups in (
            ("CG", "identity.curated", "curated_owner_list", curated_version, TIER_CURATED,
             {k: {n: [] for n in v} for k, v in curated.items()}),
            ("LG", "identity.registered_llc", "registered_llc_owner_match", llc_version, TIER_LLC, llc_sources)):
        ordered = sorted(groups.items(), key=lambda kv: (min(kv[1]), str(kv[0])))
        for i, (_, node_bbls) in enumerate(ordered, 1):
            sid = f"{prefix}{i:07d}"
            nodes = tuple(sorted(int(n) for n in node_bbls))
            sets_rows.append((sid, stage, rule, version, len(nodes)))
            for n in nodes:
                srcs = sorted(set(node_bbls[n])) or [None]
                mem_rows += [(sid, n, b) for b in srcs]
            ls.append(LinkSet(tier, stage, "link_set", sid, nodes))
    return LinkSets(pd.DataFrame(sets_rows, columns=LINK_SET_COLUMNS),
                    pd.DataFrame(mem_rows, columns=LINK_SET_MEMBER_COLUMNS), ls)


def llc_sources(conn, max_degree: int | None = None) -> dict:
    """entity -> {node: [PLUTO lots of that entity inside the node]} for every registered-LLC entity
    that reaches two or more nodes (the same entities as ``llc_edges``)."""
    from bor import llc_edges

    owners = pd.read_sql(llc_edges._owner_sql(llc_edges.DEFAULT_MAX_DEGREE if max_degree is None else max_degree), conn)
    lwc = pd.read_sql("SELECT nodeid, bbls::text[] AS bbls FROM landlords_with_connections", conn)
    bbl_node = {b: int(n) for n, bbls in zip(lwc["nodeid"], lwc["bbls"]) for b in (bbls or [])}
    out = {}
    for llc, bbls in zip(owners["llc"], owners["bbls"]):
        per: dict[int, list[str]] = defaultdict(list)
        for b in bbls or []:
            if b in bbl_node:
                per[bbl_node[b]].append(b)
        if len(per) >= 2:
            out[llc] = dict(per)
    return out


# ---- the witness --------------------------------------------------------------------------------

class _UF:
    def __init__(self, items):
        self.p = {i: i for i in items}

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def build_witness(node_group: dict, link_sets: list[LinkSet]) -> tuple[dict, list[str]]:
    """Spanning-tree steps per group, as ``{group_id: [(node_a, node_b, stage, basis_type, basis_id)]}``
    in processing order, and the groups the sets do not connect.

    ``node_group`` maps each node of each group to its group id. A set that reaches nodes of two
    different groups is a bug in the partition or in the sets and raises. Nodes outside every group
    (for example those of a group dropped as co-op dominated) are ignored."""
    uf = _UF(node_group)
    steps: dict[str, list[tuple]] = defaultdict(list)
    for s in sorted(link_sets, key=lambda s: s.order):
        nodes = [n for n in s.nodes if n in node_group]
        if len(nodes) < 2:
            continue
        groups = {node_group[n] for n in nodes}
        if len(groups) != 1:
            raise ValueError(f"{s.stage} set {s.basis_id} spans groups {sorted(groups)}")
        centre = nodes[0]
        for n in nodes[1:]:
            if uf.find(centre) != uf.find(n):
                uf.union(centre, n)
                steps[node_group[centre]].append((centre, n, s.stage, s.basis_type, s.basis_id))
    roots = defaultdict(set)
    for n, g in node_group.items():
        roots[g].add(uf.find(n))
    return dict(steps), sorted(g for g, r in roots.items() if len(r) != 1)


# ---- the tables ---------------------------------------------------------------------------------

def owner_portfolio_tables(portfolios, link_sets: list[LinkSet], run_id: str) -> tuple[dict, dict]:
    """``(tables, report)``: ``groups``, ``group_members``, ``group_bbls`` and ``group_witness`` for the
    Owner Portfolio layer. ``portfolios`` are :class:`bor.owner_portfolios.OwnerPortfolio`."""
    node_group = {int(n): p.owner_portfolio_id for p in portfolios for n in p.members}
    steps, unconnected = build_witness(node_group, link_sets)
    if unconnected:
        raise ValueError(f"{len(unconnected)} groups are not connected by their link sets, e.g. {unconnected[:3]}")

    def key(gid, suffix=""):
        return f"{run_id}/{LAYER}/{gid}{suffix}"

    groups, members, bbls, witness = [], [], [], []
    for p in sorted(portfolios, key=lambda p: p.owner_portfolio_id):
        gid = p.owner_portfolio_id
        groups.append((LAYER, gid, key(gid), p.composition, None, len(p.bbls), len(p.total_bbls)))
        members += [(LAYER, gid, int(n), key(gid, f"/n{n}")) for n in sorted(p.members)]
        rental = set(p.bbls)
        bbls += [(LAYER, gid, b, b in rental) for b in sorted(p.total_bbls)]
        for i, (a, b, stage, btype, bid) in enumerate(steps.get(gid, []), 1):
            witness.append((LAYER, gid, i, a, b, stage, btype, bid, key(gid, f"/w{i}")))
    tables = {"groups": pd.DataFrame(groups, columns=GROUP_COLUMNS),
              "group_members": pd.DataFrame(members, columns=MEMBER_COLUMNS),
              "group_bbls": pd.DataFrame(bbls, columns=BBL_COLUMNS),
              "group_witness": pd.DataFrame(witness, columns=WITNESS_COLUMNS)}
    w = tables["group_witness"]
    report = {"owner_portfolio_groups": len(groups), "owner_portfolio_nodes": len(members),
              "witness_steps": len(w),
              "witness_steps_by_stage": {k: int(v) for k, v in w.groupby("stage").size().items()},
              "groups_using_feedback": int(w.loc[w["stage"] == "identity.splink_feedback", "group_id"].nunique()),
              "groups_using_the_successor_guard": int(w.loc[w["stage"] == "deed.linked_successor", "group_id"].nunique())}
    return tables, report
