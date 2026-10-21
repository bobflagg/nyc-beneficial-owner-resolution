"""Operational Network groups, edges and paths for the release (W5).

The network layer is WCC over name, address and identity edges, then Louvain on the few components
over the size cap. Unlike the Owner Portfolio, its evidence is a weighted graph, and the whole graph is
small enough to export: **the release carries every edge** (``network_edges``, declared ``complete``),
with the exact weights Louvain was given. That serves three needs without a separate forest:

* a path between any two nodes, including two in different final networks of one original component:
  follow the edges; the ones with ``crosses_networks`` are the boundary;
* a representative path inside each network (``group_witness``): a spanning tree over its own edges,
  preferring identity edges, then name, then address, so a weaker kind is used only where needed;
* the input of Louvain, reproduced exactly (``weight = name + address + identity``).
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

LAYER = "operational_network"
EDGE_COLUMNS = ["edge_id", "component_id", "node_a", "node_b", "name_weight", "address_weight",
                "identity_weight", "weight", "crosses_networks"]
MEMBERSHIP_COLUMNS = ["node_id", "component_id", "community_id", "operational_network_id"]
SPLIT_COLUMNS = ["split_id", "component_id", "parent_community_id", "level", "outcome", "communities"]
MASKED_COLUMNS = ["address_id", "method", "normalizer_version", "degree", "degree_unit", "threshold", "decision"]
MASKED_NODE_COLUMNS = ["address_id", "node_id"]

# Which stage a path step has, by the strongest kind of evidence on the edge.
_STAGE = {"identity": "network.identity", "name": "network.name", "address": "network.address"}
_TIER = {"identity": 0, "name": 1, "address": 2}


def _kind_of(row) -> str:
    return "identity" if row.identity_weight > 0 else "name" if row.name_weight > 0 else "address"


def edge_table(entries, networks, components) -> pd.DataFrame:
    """The complete graph: one row per node pair, with each kind's summed weight. ``entries`` are
    ``(a, b, weight, kind)``; ``networks`` the final :class:`OperationalNetwork` list."""
    sums: dict[tuple[int, int], dict[str, float]] = defaultdict(lambda: {"name": 0.0, "address": 0.0, "identity": 0.0})
    for a, b, w, kind in entries:
        if a == b:
            continue
        sums[(a, b) if a < b else (b, a)][kind] += w
    comp_of = {n: f"NC-{min(c)}" for c in components for n in c}
    net_of = {n: net.operational_network_id for net in networks for n in net.members}
    rows = []
    for i, ((a, b), k) in enumerate(sorted(sums.items()), 1):
        rows.append((f"NE{i:07d}", comp_of[a], a, b, k["name"], k["address"], k["identity"],
                     k["name"] + k["address"] + k["identity"], net_of[a] != net_of[b]))
    return pd.DataFrame(rows, columns=EDGE_COLUMNS)


def membership_table(networks, components) -> pd.DataFrame:
    comp_of = {n: f"NC-{min(c)}" for c in components for n in c}
    rows = []
    for net in networks:
        for n in net.members:
            rows.append((n, comp_of[n], net.operational_network_id if net.split == "louvain" else None,
                         net.operational_network_id))
    return pd.DataFrame(rows, columns=MEMBERSHIP_COLUMNS).sort_values("node_id").reset_index(drop=True)


def split_table(attempts) -> pd.DataFrame:
    rows = []
    for i, a in enumerate(sorted(attempts, key=lambda a: (a["component"], a["level"],
                                                          a["parent"] or (0, 0))), 1):
        parent = None if a["parent"] is None else f"NM-{a['parent'][0]}-L{a['parent'][1]}"
        rows.append((f"SP{i:07d}", f"NC-{a['component']}", parent, a["level"], a["outcome"], a["communities"]))
    return pd.DataFrame(rows, columns=SPLIT_COLUMNS)


def witness_table(networks, edges: pd.DataFrame, run_id: str) -> tuple[list, dict]:
    """Spanning-forest steps per network over its own edges, strongest evidence first, and the number
    of connected pieces each network's path leaves (``{group_id: pieces}``).

    Louvain does not guarantee a community is connected by its own edges, and a step never leaves the
    network, so a network can have more than one piece (a spanning tree has exactly one). The
    complete ``network_edges`` table still connects the pieces, through nodes of other networks, with
    the boundary marked."""
    by_net = {n: net.operational_network_id for net in networks for n in net.members}
    inner = defaultdict(list)
    for r in edges.itertuples():
        if by_net[r.node_a] == by_net[r.node_b]:
            inner[by_net[r.node_a]].append(r)
    witness, pieces = [], {}
    for net in sorted(networks, key=lambda n: n.operational_network_id):
        gid = net.operational_network_id
        parent = {n: n for n in net.members}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        step = 0
        for r in sorted(inner.get(gid, []), key=lambda r: (_TIER[_kind_of(r)], r.edge_id)):
            ra, rb = find(r.node_a), find(r.node_b)
            if ra != rb:
                parent[ra] = rb
                step += 1
                witness.append((LAYER, gid, step, r.node_a, r.node_b, _STAGE[_kind_of(r)], "network_edge",
                                r.edge_id, f"{run_id}/{LAYER}/{gid}/w{step}"))
        pieces[gid] = len({find(n) for n in net.members})
    return witness, pieces


def masked_tables(aggregators: dict, normalizer_version: str, threshold: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """``(masked_addresses, masked_address_nodes, events)``: the aggregator addresses masked from the
    address edges. Ids are opaque (numbered by smallest node); the address strings are not exported."""
    from bor.identity_events import EVENT_COLUMNS

    ordered = sorted(aggregators.items(), key=lambda kv: (min(kv[1]), kv[0]))
    masked, nodes, events = [], [], []
    for i, (_, ns) in enumerate(ordered, 1):
        aid = f"A{i:07d}"
        masked.append((aid, "network_address_edge_mask", normalizer_version, len(ns),
                       "landlords (lwc nodes)", threshold, "masked"))
        nodes += [(aid, n) for n in ns]
        row = dict.fromkeys(EVENT_COLUMNS)
        row.update(layer=LAYER, stage="network.address", subject_type="address", subject_id=aid,
                   outcome="masked", reason_code="aggregator_address_masked", rule="aggregator_address_mask",
                   rule_version=normalizer_version, detail=f'{{"degree": {len(ns)}, "threshold": {threshold}}}')
        events.append(row)
    ev = pd.DataFrame(events, columns=EVENT_COLUMNS)
    ev["decision_id"] = [f"N{i:07d}" for i in range(1, len(ev) + 1)]
    return (pd.DataFrame(masked, columns=MASKED_COLUMNS), pd.DataFrame(nodes, columns=MASKED_NODE_COLUMNS), ev)


def network_tables(networks, trace: dict, run_id: str) -> tuple[dict, dict]:
    """The Operational Network layer: ``network_edges``, ``network_membership``, ``split_attempts`` and
    ``groups``, ``group_members``, ``group_bbls``, ``group_witness`` for ``layer = operational_network``."""
    components = trace["components"]
    edges = edge_table(trace["entries"], networks, components)
    witness, pieces = witness_table(networks, edges, run_id)

    def key(gid, suffix=""):
        return f"{run_id}/{LAYER}/{gid}{suffix}"

    groups, members, bbls = [], [], []
    for net in sorted(networks, key=lambda n: n.operational_network_id):
        gid = net.operational_network_id
        groups.append((LAYER, gid, key(gid), None, net.split, len(net.bbls), len(net.bbls), pieces[gid]))
        members += [(LAYER, gid, int(n), key(gid, f"/n{n}")) for n in sorted(net.members)]
        bbls += [(LAYER, gid, b, True) for b in net.bbls]     # no co-op filter in this layer: all lots are rental
    from bor import group_tables as gt
    tables = {
        "network_edges": edges,
        "network_membership": membership_table(networks, components),
        "split_attempts": split_table(trace["attempts"]),
        "groups": pd.DataFrame(groups, columns=gt.GROUP_COLUMNS),
        "group_members": pd.DataFrame(members, columns=gt.MEMBER_COLUMNS),
        "group_bbls": pd.DataFrame(bbls, columns=gt.BBL_COLUMNS),
        "group_witness": pd.DataFrame(witness, columns=gt.WITNESS_COLUMNS),
    }
    split = tables["split_attempts"]
    report = {"operational_networks": len(groups), "components": len(components),
              "network_edges": len(edges), "edges_crossing_networks": int(edges["crosses_networks"].sum()),
              "louvain_networks": sum(1 for g in groups if g[4] == "louvain"),
              "split_attempts": len(split), "split_attempts_without_a_useful_split": int((split["outcome"] == "no_split").sum()),
              "networks_not_connected_by_their_own_edges": sum(1 for p in pieces.values() if p > 1),
              "witness_steps": len(witness)}
    return tables, report
