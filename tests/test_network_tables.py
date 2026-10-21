"""Operational Network edges, boundary, paths and masked addresses (no database), then the reference dump."""
from types import SimpleNamespace

import pandas as pd
import pytest

from bor import network_tables as nt
from bor import operational_network as on
from bor.release_validate import validate_release


def _net(nid, members, bbls=None, split="wcc"):
    return SimpleNamespace(operational_network_id=nid, members=list(members),
                           bbls=list(bbls if bbls is not None else [f"B{m}" for m in members]), split=split)


# --- the edge table ------------------------------------------------------------------------------

def test_edge_weights_sum_every_contribution_and_split_by_kind():
    entries = [(1, 2, 1.5, "name"), (2, 1, 1.5, "name"),            # the lwc JSON lists mutual matches twice
               (1, 2, 1.0, "address"), (1, 2, 100.0, "identity"), (2, 3, 1.0, "address")]
    nets = [_net("ON-1", [1, 2, 3])]
    e = nt.edge_table(entries, nets, [[1, 2, 3]]).set_index(["node_a", "node_b"])
    r = e.loc[(1, 2)]
    assert (r["name_weight"], r["address_weight"], r["identity_weight"], r["weight"]) == (3.0, 1.0, 100.0, 104.0)
    assert e.loc[(2, 3), "weight"] == 1.0 and set(e.index) == {(1, 2), (2, 3)}
    assert all(a < b for a, b in e.index)


def test_the_collapsed_weight_matches_what_louvain_is_given():
    entries = [(1, 2, 1.5, "name"), (2, 1, 1.5, "name"), (1, 2, 1.0, "address"), (3, 2, 100.0, "identity")]
    e = nt.edge_table(entries, [_net("ON-1", [1, 2, 3])], [[1, 2, 3]])
    legacy = on._collapse([(a, b, w) for a, b, w, _ in entries])
    assert dict(zip(zip(e["node_a"], e["node_b"]), e["weight"])) == dict(legacy)


def test_an_edge_between_two_final_networks_is_marked_as_the_boundary():
    nets = [_net("ON-1", [1, 2], split="louvain"), _net("ON-3", [3, 4], split="louvain")]
    e = nt.edge_table([(1, 2, 100.0, "identity"), (2, 3, 1.5, "name"), (3, 4, 100.0, "identity")], nets, [[1, 2, 3, 4]])
    assert dict(zip(zip(e["node_a"], e["node_b"]), e["crosses_networks"])) == {(1, 2): False, (2, 3): True, (3, 4): False}
    assert set(e["component_id"]) == {"NC-1"}


def test_membership_names_the_component_and_the_community_only_when_split():
    nets = [_net("ON-1", [1, 2], split="louvain"), _net("ON-3", [3, 4], split="louvain"), _net("ON-9", [9, 10])]
    m = nt.membership_table(nets, [[1, 2, 3, 4], [9, 10]]).set_index("node_id")
    assert m.loc[2, "component_id"] == "NC-1" and m.loc[2, "community_id"] == "ON-1" and m.loc[4, "operational_network_id"] == "ON-3"
    assert m.loc[9, "component_id"] == "NC-9" and pd.isna(m.loc[9, "community_id"])


def test_split_attempts_record_the_levels_and_the_no_split_outcomes():
    attempts = [{"component": 1, "parent": None, "level": 0, "outcome": "split", "communities": 3},
                {"component": 1, "parent": (1, 0), "level": 1, "outcome": "no_split", "communities": 1}]
    s = nt.split_table(attempts)
    assert list(s["outcome"]) == ["split", "no_split"] and list(s["level"]) == [0, 1]
    assert pd.isna(s["parent_community_id"].iloc[0]) and s["parent_community_id"].iloc[1] == "NM-1-L0"
    assert s["split_id"].is_unique


# --- the path inside a network -------------------------------------------------------------------

def _edges(rows):
    return pd.DataFrame(rows, columns=["edge_id", "component_id", "node_a", "node_b", "name_weight",
                                       "address_weight", "identity_weight", "weight", "crosses_networks"])


def test_the_path_prefers_identity_then_name_then_address_edges():
    edges = _edges([("NE1", "NC-1", 1, 2, 0, 1.0, 0, 1.0, False),        # address only
                    ("NE2", "NC-1", 1, 2, 3.0, 0, 0, 3.0, False),        # a name edge between the same pair
                    ("NE3", "NC-1", 2, 3, 0, 1.0, 0, 1.0, False),
                    ("NE4", "NC-1", 2, 3, 0, 0, 100.0, 100.0, False),    # an identity edge
                    ("NE5", "NC-1", 1, 3, 0, 1.0, 0, 1.0, False)])
    steps, pieces = nt.witness_table([_net("ON-1", [1, 2, 3])], edges, "r")
    assert pieces == {"ON-1": 1}
    assert [(s[3], s[4], s[5], s[7]) for s in steps] == [(2, 3, "network.identity", "NE4"), (1, 2, "network.name", "NE2")]
    assert len(steps) == 2 and all(s[6] == "network_edge" for s in steps)         # a tree: members - 1


def test_a_path_never_leaves_its_network():
    edges = _edges([("NE1", "NC-1", 1, 2, 1.5, 0, 0, 1.5, False), ("NE2", "NC-1", 2, 3, 1.5, 0, 0, 1.5, True)])
    steps, pieces = nt.witness_table([_net("ON-1", [1, 2], split="louvain"), _net("ON-3", [3], split="louvain")], edges, "r")
    assert [s[7] for s in steps] == ["NE1"] and pieces == {"ON-1": 1, "ON-3": 1}   # the crossing edge is not a step


def test_a_network_its_own_edges_do_not_connect_has_a_forest_and_says_how_many_pieces():
    """Louvain can make a community that is not internally connected; its path is then a forest."""
    edges = _edges([("NE1", "NC-1", 1, 2, 1.5, 0, 0, 1.5, False), ("NE2", "NC-1", 2, 3, 1.5, 0, 0, 1.5, True),
                    ("NE3", "NC-1", 3, 4, 1.5, 0, 0, 1.5, True)])
    nets = [_net("ON-1", [1, 2, 4], split="louvain"), _net("ON-3", [3], split="louvain")]
    steps, pieces = nt.witness_table(nets, edges, "r")
    assert pieces == {"ON-1": 2, "ON-3": 1} and len(steps) == 1                 # nodes 1-2 joined; node 4 stands alone
    t, rep = nt.network_tables(nets, {"components": [[1, 2, 3, 4]], "attempts": [],
                               "entries": [(1, 2, 1.5, "name"), (2, 3, 1.5, "name"), (3, 4, 1.5, "name")]}, "r")
    g = t["groups"].set_index("group_id")
    assert g.loc["ON-1", "witness_pieces"] == 2 and g.loc["ON-3", "witness_pieces"] == 1
    assert rep["networks_not_connected_by_their_own_edges"] == 1


# --- masked addresses ----------------------------------------------------------------------------

def test_masked_addresses_are_opaque_and_carry_degree_and_nodes():
    masked, nodes, events = nt.masked_tables({"1 MAIN ST 5 FL": [9, 4, 7], "50 BROAD ST": [2, 3]}, "norm-v1", 25)
    assert list(masked["address_id"]) == ["A0000001", "A0000002"]                 # numbered by smallest node
    assert masked.set_index("address_id").loc["A0000001", "degree"] == 2 and not masked.astype(str).apply(
        lambda c: c.str.contains("BROAD|MAIN")).any().any()
    assert sorted(nodes[nodes["address_id"] == "A0000002"]["node_id"]) == [4, 7, 9]
    assert set(events["reason_code"]) == {"aggregator_address_masked"} and (events["layer"] == "operational_network").all()


# --- the resolver records its work without changing it -------------------------------------------

class _Cursor:
    def __init__(self, rows): self.rows = rows
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql): self.sql = sql
    def __iter__(self):
        return iter(self.rows[self.sql])


class _Conn:
    def __init__(self, rows): self.rows = rows
    def cursor(self, name=None): return _Cursor(self.rows)


def _resolver_setup(monkeypatch):
    nodes = list(range(1, 9))
    rows = {on._BBL_COUNT_SQL: [(n, 70) for n in nodes] + [(20, 70), (21, 70)],      # 560 lots: over the cap of 300
            on._NODE_BBL_SQL: [(n, [f"B{n}"]) for n in nodes] + [(20, ["B20"]), (21, ["B21"])]}
    edges = [(i, i + 1, 1.5) for i in range(1, 8)] + [(20, 21, 1.5)]
    monkeypatch.setattr(on, "_aggregator_nodes", lambda conn: set())
    monkeypatch.setattr(on, "_name_address_edges", lambda conn, agg, kinds=False: [e + ("name",) if kinds else e for e in edges])
    monkeypatch.setattr(on, "_splink_edges", lambda conn, **kw: [(1, 2, 100.0)])
    monkeypatch.setattr(on, "_louvain_communities",
                        lambda ids, w, seed=None: [[n for n in ids if n <= 4], [n for n in ids if n > 4]])
    return _Conn(rows)


def test_tracing_records_components_attempts_and_edges_and_changes_no_network(monkeypatch):
    conn = _resolver_setup(monkeypatch)
    plain = on.resolve_operational_networks(conn)
    trace = {}
    traced = on.resolve_operational_networks(conn, trace=trace)
    assert [(n.operational_network_id, n.members, n.split) for n in plain] == [
        (n.operational_network_id, n.members, n.split) for n in traced]
    assert [n.operational_network_id for n in traced] == ["ON-1", "ON-20", "ON-5"]
    assert sorted(map(tuple, trace["components"])) == [(1, 2, 3, 4, 5, 6, 7, 8), (20, 21)]
    assert trace["attempts"] == [{"component": 1, "parent": None, "level": 0, "outcome": "split", "communities": 2}]
    kinds = {k for *_, k in trace["entries"]}
    assert kinds == {"name", "identity"}


def test_the_whole_layer_satisfies_the_contract(monkeypatch):
    conn = _resolver_setup(monkeypatch)
    trace = {}
    nets = on.resolve_operational_networks(conn, trace=trace)
    t, rep = nt.network_tables(nets, trace, "run-1")
    assert rep["operational_networks"] == 3 and rep["louvain_networks"] == 2 and rep["edges_crossing_networks"] == 1
    assert len(t["group_witness"]) == sum(len(n.members) - 1 for n in nets)       # every path is a tree
    masked, mnodes, mev = nt.masked_tables({"X": [3, 4]}, "v", 25)
    node_obs = pd.DataFrame({"node_id": [1, 2, 3, 4, 5, 6, 7, 8, 20, 21]})
    node_obs["bbl"] = [f"B{n}" for n in node_obs["node_id"]]
    node_obs["registration_id"], node_obs["n_candidates"], node_obs["selected_observation_id"] = 1, 0, None
    node_obs["ambiguous"] = False
    observations = pd.DataFrame(columns=["observation_id", "registration_id", "registration_contact_id", "k", "pair_variants"])
    tables = dict(t, observations=observations, node_observations=node_obs, masked_addresses=masked,
                  masked_address_nodes=mnodes, decision_events=mev)
    errors = [v for v in validate_release(tables, check_manifest_too=False) if v.severity == "error"]
    assert errors == [], errors


def test_the_validator_catches_a_wrong_boundary_flag_and_a_wrong_weight(monkeypatch):
    conn = _resolver_setup(monkeypatch)
    trace = {}
    nets = on.resolve_operational_networks(conn, trace=trace)
    t, _ = nt.network_tables(nets, trace, "r")
    bad = {k: v.copy() for k, v in t.items()}
    bad["network_edges"].loc[0, "crosses_networks"] = not bad["network_edges"].loc[0, "crosses_networks"]
    bad["network_edges"].loc[1, "weight"] = 999.0
    checks = {(v.table, v.check) for v in validate_release(bad, check_manifest_too=False) if v.severity == "error"}
    assert {("network_edges", "boundary"), ("network_edges", "weight")} <= checks


def test_the_validator_checks_the_number_of_pieces_a_path_leaves():
    nets = [_net("ON-1", [1, 2, 4], split="louvain"), _net("ON-3", [3], split="louvain")]
    t, _ = nt.network_tables(nets, {"components": [[1, 2, 3, 4]], "attempts": [],
                             "entries": [(1, 2, 1.5, "name"), (2, 3, 1.5, "name"), (3, 4, 1.5, "name")]}, "r")
    node_obs = pd.DataFrame({"node_id": [1, 2, 3, 4], "bbl": [f"B{n}" for n in (1, 2, 3, 4)]})
    node_obs["registration_id"], node_obs["n_candidates"], node_obs["selected_observation_id"] = 1, 0, None
    node_obs["ambiguous"] = False
    observations = pd.DataFrame(columns=["observation_id", "registration_id", "registration_contact_id", "k", "pair_variants"])
    ok = dict(t, node_observations=node_obs, observations=observations)
    assert [v for v in validate_release(ok, check_manifest_too=False) if v.severity == "error"] == []
    lie = {k: v.copy() for k, v in ok.items()}
    lie["groups"].loc[lie["groups"]["group_id"] == "ON-1", "witness_pieces"] = 1       # claims a tree
    assert ("group_witness", "tree") in {(v.table, v.check) for v in validate_release(lie, check_manifest_too=False)}


# --- the reference dump: a whole release (needs the database) ----------------------------------

def _tables(release_build):
    from bor.release_validate import read_release
    out, _ = release_build
    return read_release(str(out))


def test_operational_network_layer_on_the_reference_dump(release_build):
    from tests import expected as E
    _, r = release_build
    assert [v for v in r["violations"] if v.severity == "error"] == []
    t, manifest = _tables(release_build)
    g = t["groups"]
    nets = g[g["layer"] == "operational_network"]
    assert abs(len(nets) - E.OPERATIONAL_NETWORKS_MULTI) <= E.TOL and nets["group_id"].str.startswith("ON-").all()
    assert abs(len(t["network_edges"]) - 57_202) <= 200                         # measured by the W5 size spike
    assert manifest["artifacts"]["network_edges"] == "complete" and manifest["artifacts"]["group_witness"] == "representative"
    # each network's path is a forest with exactly the pieces its group declares (one, a tree, unless
    # Louvain made a community that its own edges do not connect)
    w = t["group_witness"]
    w = w[w["layer"] == "operational_network"]
    members = t["group_members"]
    members = members[members["layer"] == "operational_network"]
    steps = w.groupby("group_id").size().reindex(nets["group_id"]).fillna(0).astype(int)
    size = members.groupby("group_id").size().reindex(nets["group_id"])
    pieces = nets.set_index("group_id")["witness_pieces"].astype(int).reindex(nets["group_id"])
    assert (steps.to_numpy() == (size - pieces).to_numpy()).all()
    # weights are the exact sum of the parts
    e = t["network_edges"]                                   # read_release leaves every column as text
    w, nm, ad, idw = (pd.to_numeric(e[c]) for c in ("weight", "name_weight", "address_weight", "identity_weight"))
    assert ((w - (nm + ad + idw)).abs() < 1e-6).all()
    assert pd.to_numeric(t["masked_addresses"]["degree"]).min() > 25 and len(t["masked_address_nodes"]) > 0


def test_two_lots_in_different_networks_of_one_component_have_a_path_with_the_boundary_marked(release_build):
    from collections import deque
    t, _ = _tables(release_build)
    mem, e = t["network_membership"], t["network_edges"]
    per = mem.groupby("component_id")["operational_network_id"].nunique()
    split_components = per[per > 1].index
    assert len(split_components), "expected components that Louvain cut into several networks"
    comp = mem[mem["component_id"] == split_components[0]]
    nodes = comp["node_id"].tolist()
    net = dict(zip(comp["node_id"], comp["operational_network_id"]))
    start = nodes[0]
    goal = next(n for n in nodes if net[n] != net[start])
    # breadth-first over the exported edges
    adj = {}
    for a, b, eid, cross in zip(e["node_a"], e["node_b"], e["edge_id"], e["crosses_networks"]):
        adj.setdefault(a, []).append((b, eid, cross))
        adj.setdefault(b, []).append((a, eid, cross))
    prev, queue = {start: None}, deque([start])
    while queue and goal not in prev:
        u = queue.popleft()
        for v, eid, cross in adj.get(u, []):
            if v not in prev:
                prev[v] = (u, eid, cross)
                queue.append(v)
    assert goal in prev, "two nodes of one component must be connected by the exported edges"
    path, n = [], goal
    while prev[n] is not None:
        u, eid, cross = prev[n]
        path.append((u, n, eid, cross))
        n = u
    assert any(cross == "True" for *_, cross in path)                       # the boundary is identified
    assert len({net[x] for x in [start, goal]}) == 2


def test_masked_addresses_have_decisions_and_no_address_text(release_build):
    t, _ = _tables(release_build)
    ev = t["decision_events"]
    masks = ev[ev["rule"] == "aggregator_address_mask"]
    assert len(masks) == len(t["masked_addresses"]) > 0
    assert (masks["layer"] == "operational_network").all() and set(masks["subject_type"]) == {"address"}
    assert t["masked_addresses"]["address_id"].str.fullmatch(r"A\d{7}").all()


# --- Louvain is seeded --------------------------------------------------------------------------

def _ring_graph():
    """Two overlapping rings: enough ambiguity that Louvain's visiting order changes the answer."""
    w = {}
    for i in range(60):
        for step, weight in ((1, 1.0), (7, 0.8)):
            a, b = i, (i + step) % 60
            w[(min(a, b), max(a, b))] = weight
    return list(range(60)), w


def test_louvain_gives_the_same_communities_for_the_same_seed():
    ids, w = _ring_graph()
    norm = lambda comms: sorted(sorted(c) for c in comms)
    results = {repr(norm(on._louvain_communities(ids, w, seed=1))) for _ in range(6)}
    assert len(results) == 1


def test_the_seed_matters_so_it_has_to_be_recorded():
    ids, w = _ring_graph()
    norm = lambda comms: sorted(sorted(c) for c in comms)
    assert len({repr(norm(on._louvain_communities(ids, w, seed=s))) for s in range(10)}) > 1


def test_seeding_louvain_leaves_the_global_random_state_alone():
    import random
    ids, w = _ring_graph()
    random.seed(123)
    expected = random.random()
    random.seed(123)
    on._louvain_communities(ids, w, seed=5)
    assert random.random() == expected


def test_the_seed_is_part_of_the_resolver_and_the_manifest_parameters():
    import inspect

    from bor import manifest as mf
    assert inspect.signature(on.resolve_operational_networks).parameters["seed"].default == on.LOUVAIN_SEED == 42
    params = mf.parameters({"threshold": 0.999}, __import__("datetime").date(2026, 10, 21))
    assert params["operational_network"]["louvain_seed"] == 42


def test_networks_are_reproducible_on_the_reference_dump(pg, release_build):
    """The release was built once; resolving the layer again from the same clusters gives the same networks."""
    t, _ = _tables(release_build)
    nc = t["node_cluster"][["node_id", "cluster_id"]].rename(columns={"node_id": "nodeid"})
    nc["nodeid"] = nc["nodeid"].astype(int)
    again = on.resolve_operational_networks(pg, node_cluster_frame=nc)
    gm = t["group_members"]
    gm = gm[gm["layer"] == "operational_network"]
    released = {gid: set(g["node_id"].astype(int)) for gid, g in gm.groupby("group_id")}
    assert {n.operational_network_id: set(n.members) for n in again} == released
