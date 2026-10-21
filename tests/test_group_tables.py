"""Owner Portfolios and witness paths: link sets, the spanning tree and the tables (no database)."""
from types import SimpleNamespace

import pandas as pd
import pytest

from bor import group_tables as gt
from bor.group_tables import LinkSet


def _portfolio(gid, members, rental=None, total=None, composition="identity"):
    total = total or [f"B{m}" for m in members]
    return SimpleNamespace(owner_portfolio_id=gid, members=list(members), bbls=list(rental if rental is not None else total),
                           total_bbls=list(total), composition=composition)


def _tree_ok(steps, members):
    """A path is a tree: one step fewer than members, connecting exactly the members."""
    parent = {m: m for m in members}

    def find(x):
        while parent[x] != x:
            x = parent[x]
        return x

    for a, b, *_ in steps:
        assert a in parent and b in parent
        assert find(a) != find(b), "a step closed a cycle"
        parent[find(a)] = find(b)
    assert len({find(m) for m in members}) == 1
    assert len(steps) == len(members) - 1


# --- identity clusters: base steps first, the feedback step only where needed --------------------

def _cluster_inputs():
    """Cluster C joins nodes 1,2 (one base cluster) and node 3 (another), by a shared company."""
    nc = pd.DataFrame({"node_id": [1, 2, 3], "cluster_id": ["C1"] * 3})
    matches = pd.DataFrame({"node_id": [1, 2, 3], "identity_id": ["Ia", "Ib", "Ic"]})
    ic = pd.DataFrame({"identity_id": ["Ia", "Ib", "Ic"], "cluster_id": ["C1"] * 3,
                       "base_cluster_id": ["BC1", "BC1", "BC2"]})
    return nc, matches, ic


def test_a_cluster_gives_base_sets_then_one_feedback_set():
    sets = gt.cluster_link_sets(*_cluster_inputs())
    got = {(s.stage, s.nodes) for s in sets}
    assert got == {("identity.splink_base", (1, 2)), ("identity.splink_feedback", (1, 2, 3))}
    assert all(s.basis_type == "identity_cluster" and s.basis_id == "C1" for s in sets)


def test_the_path_uses_the_feedback_stage_only_for_the_step_that_needs_it():
    sets = gt.cluster_link_sets(*_cluster_inputs())
    steps, bad = gt.build_witness({1: "G", 2: "G", 3: "G"}, sets)
    assert bad == []
    assert [(a, b, st) for a, b, st, *_ in steps["G"]] == [(1, 2, "identity.splink_base"), (1, 3, "identity.splink_feedback")]
    _tree_ok(steps["G"], [1, 2, 3])


def test_a_node_that_matched_an_identity_outside_its_assigned_cluster_does_not_use_that_base_cluster():
    nc, matches, ic = _cluster_inputs()
    matches = pd.concat([matches, pd.DataFrame({"node_id": [3], "identity_id": ["Ix"]})])
    ic = pd.concat([ic, pd.DataFrame({"identity_id": ["Ix"], "cluster_id": ["C9"], "base_cluster_id": ["BC1"]})])
    sets = gt.cluster_link_sets(nc, matches, ic)
    assert ("identity.splink_base", (1, 2)) in {(s.stage, s.nodes) for s in sets}      # node 3 is not pulled into BC1


# --- the order prefers strong evidence ----------------------------------------------------------

def test_weak_evidence_is_used_only_when_the_strong_cannot_connect_the_group():
    strong = LinkSet(gt.TIER_LLC, "identity.registered_llc", "link_set", "LG1", (1, 2, 3))
    weak = LinkSet(gt.TIER_DEED_GUARD, "deed.linked_successor", "evidence_item", "DV1", (1, 2, 3))
    steps, _ = gt.build_witness({1: "G", 2: "G", 3: "G"}, [weak, strong])
    assert {s[2] for s in steps["G"]} == {"identity.registered_llc"}                   # the guard is not needed

    partial = LinkSet(gt.TIER_LLC, "identity.registered_llc", "link_set", "LG1", (1, 2))
    steps, _ = gt.build_witness({1: "G", 2: "G", 3: "G"}, [weak, partial])
    assert [s[2] for s in steps["G"]] == ["identity.registered_llc", "deed.linked_successor"]


def test_the_tiers_run_in_the_documented_order():
    assert (gt.TIER_BASE < gt.TIER_CURATED < gt.TIER_LLC < gt.TIER_DEED_HELD
            < gt.TIER_FEEDBACK < gt.TIER_DEED_GUARD)


# --- deeds ---------------------------------------------------------------------------------------

def _deed(rows):
    items = pd.DataFrame({"evidence_id": sorted({r[0] for r in rows})})
    members = pd.DataFrame(rows, columns=["evidence_id", "node_id", "role", "excluded_reason"])
    return items, members


def test_a_deed_connects_held_nodes_first_and_guard_nodes_through_a_weaker_step():
    _, members = _deed([("DV1", 1, "held_under_joint_deed", None), ("DV1", 2, "held_under_joint_deed", None),
                        ("DV1", 3, "transferred_onward", None)])
    sets = gt.deed_link_sets(None, members)
    assert {(s.stage, s.nodes) for s in sets} == {("deed.held_since", (1, 2)), ("deed.linked_successor", (1, 2, 3))}
    steps, _ = gt.build_witness({1: "G", 2: "G", 3: "G"}, sets)
    assert [(a, b, st) for a, b, st, *_ in steps["G"]] == [(1, 2, "deed.held_since"), (1, 3, "deed.linked_successor")]


def test_hub_nodes_are_left_out_of_a_deeds_sets():
    _, members = _deed([("DV1", 1, "held_under_joint_deed", None), ("DV1", 2, "held_under_joint_deed", None),
                        ("DV1", 9, "held_under_joint_deed", "deed_hub_capped")])
    sets = gt.deed_link_sets(None, members)
    assert [s.nodes for s in sets] == [(1, 2)]


def test_a_deed_whose_only_link_is_the_guard_has_a_guard_centre_on_a_direct_holder():
    _, members = _deed([("DV1", 5, "held_under_joint_deed", None), ("DV1", 3, "transferred_onward", None)])
    (s,) = gt.deed_link_sets(None, members)
    assert s.stage == "deed.linked_successor" and s.nodes == (5, 3)


# --- curated and registered-LLC sets ------------------------------------------------------------

def test_named_sets_get_opaque_ids_numbered_by_smallest_node_and_cite_their_source_lots():
    s = gt.named_link_sets({"some-owner-label": {7, 9}}, {"BEACH 99TH LLC": {4: ["B40"], 2: ["B20", "B21"]}}, "c-v1", "l-v1")
    assert list(s.sets["set_id"]) == ["CG0000001", "LG0000001"]
    exported = " ".join(str(v) for df in (s.sets, s.members) for v in df.to_numpy().ravel())
    assert "BEACH" not in exported and "some-owner-label" not in exported                          # no names leave
    llc = s.members[s.members["set_id"] == "LG0000001"]
    assert sorted(zip(llc["node_id"], llc["source_bbl"])) == [(2, "B20"), (2, "B21"), (4, "B40")]
    cur = s.members[s.members["set_id"] == "CG0000001"]
    assert cur["source_bbl"].isna().all()
    assert [l.nodes for l in s.link_sets] == [(7, 9), (2, 4)]


# --- the witness is a tree, and refuses an inconsistent partition ------------------------------

def test_every_group_gets_a_spanning_tree_whatever_the_input_order():
    sets = [LinkSet(gt.TIER_LLC, "identity.registered_llc", "link_set", "LG1", (1, 2, 3, 4)),
            LinkSet(gt.TIER_LLC, "identity.registered_llc", "link_set", "LG2", (5, 6)),
            LinkSet(gt.TIER_DEED_HELD, "deed.held_since", "evidence_item", "DV1", (4, 5))]
    ng = {1: "G1", 2: "G1", 3: "G1", 4: "G1", 5: "G1", 6: "G1"}
    a, bad = gt.build_witness(ng, sets)
    b, _ = gt.build_witness(ng, list(reversed(sets)))
    assert bad == [] and a == b
    _tree_ok(a["G1"], [1, 2, 3, 4, 5, 6])


def test_a_set_spanning_two_groups_is_an_error():
    with pytest.raises(ValueError, match="spans groups"):
        gt.build_witness({1: "G1", 2: "G2"}, [LinkSet(gt.TIER_LLC, "identity.registered_llc", "link_set", "LG1", (1, 2))])


def test_a_group_the_sets_do_not_connect_is_reported():
    steps, bad = gt.build_witness({1: "G", 2: "G", 3: "G"},
                                  [LinkSet(gt.TIER_LLC, "identity.registered_llc", "link_set", "LG1", (1, 2))])
    assert bad == ["G"]


def test_nodes_of_a_dropped_group_are_ignored():
    steps, bad = gt.build_witness({1: "G", 2: "G"},
                                  [LinkSet(gt.TIER_LLC, "identity.registered_llc", "link_set", "LG1", (1, 2, 8, 9))])
    assert bad == [] and len(steps["G"]) == 1


# --- the tables ---------------------------------------------------------------------------------

def test_tables_carry_counts_lots_keys_and_the_path():
    p = _portfolio("OP-1", [1, 2, 3], rental=["B1", "B2"], total=["B1", "B2", "B3"], composition="deed_bridged")
    sets = [LinkSet(gt.TIER_LLC, "identity.registered_llc", "link_set", "LG1", (1, 2, 3))]
    t, rep = gt.owner_portfolio_tables([p], sets, "run-7")
    g = t["groups"].iloc[0]
    assert (g["layer"], g["group_id"], g["composition"], g["lot_count"], g["total_lot_count"]) == (
        "owner_portfolio", "OP-1", "deed_bridged", 2, 3)
    assert g["assertion_key"] == "run-7/owner_portfolio/OP-1" and pd.isna(g["split"])
    assert list(t["group_members"]["assertion_key"]) == [f"run-7/owner_portfolio/OP-1/n{n}" for n in (1, 2, 3)]
    assert dict(zip(t["group_bbls"]["bbl"], t["group_bbls"]["rental"])) == {"B1": True, "B2": True, "B3": False}
    assert list(t["group_witness"]["assertion_key"]) == ["run-7/owner_portfolio/OP-1/w1", "run-7/owner_portfolio/OP-1/w2"]
    assert rep["witness_steps"] == 2 and rep["groups_using_feedback"] == 0


def test_a_node_whose_lots_are_all_co_op_stays_a_member_and_a_path_node():
    p = _portfolio("OP-1", [1, 2, 3], rental=["B1", "B2"], total=["B1", "B2", "B3"])
    sets = [LinkSet(gt.TIER_LLC, "identity.registered_llc", "link_set", "LG1", (1, 2)),
            LinkSet(gt.TIER_DEED_HELD, "deed.held_since", "evidence_item", "DV1", (2, 3))]
    t, _ = gt.owner_portfolio_tables([p], sets, "r")
    assert 3 in set(t["group_members"]["node_id"]) and 3 in set(t["group_witness"]["node_b"])
    assert not t["group_bbls"].set_index("bbl").loc["B3", "rental"]


def test_an_unconnected_group_stops_the_build():
    with pytest.raises(ValueError, match="not connected"):
        gt.owner_portfolio_tables([_portfolio("OP-1", [1, 2, 3])],
                                  [LinkSet(gt.TIER_LLC, "identity.registered_llc", "link_set", "LG1", (1, 2))], "r")


# --- the reference dump: a whole release (needs the database) ----------------------------------

def test_owner_portfolio_groups_on_the_reference_dump(release_build):
    from tests import expected as E

    from bor.release_validate import read_release
    out, r = release_build
    assert [v for v in r["violations"] if v.severity == "error"] == []
    t, _ = read_release(str(out))
    op = lambda df: df[df["layer"] == "owner_portfolio"]          # the release also holds the Operational Networks
    groups, members, witness, lots = (op(t[n]) for n in ("groups", "group_members", "group_witness", "group_bbls"))
    assert abs(len(groups) - E.OWNER_PORTFOLIOS) <= E.TOL and abs(len(members) - E.OWNER_PORTFOLIO_NODES) <= E.TOL
    comp = groups["composition"].value_counts()
    for kind, want in E.COMPOSITION.items():
        assert abs(int(comp.get(kind, 0)) - want) <= E.TOL, (kind, comp.get(kind), want)
    # every Owner Portfolio's path is a tree: exactly one step fewer than its members
    steps = witness.groupby("group_id").size().reindex(groups["group_id"]).fillna(0).astype(int)
    size = members.groupby("group_id").size().reindex(groups["group_id"])
    assert (steps.to_numpy() == (size - 1).to_numpy()).all() and (groups["witness_pieces"].astype(int) == 1).all()
    # a BBL is in at most one Owner Portfolio, and ids carry their prefix
    assert not lots.duplicated("bbl").any() and groups["group_id"].str.startswith("OP-").all()


def test_the_paths_use_every_kind_of_evidence_and_cite_it(release_build):
    from bor.release_validate import read_release
    out, _ = release_build
    t, _ = read_release(str(out))
    w = t["group_witness"]
    w = w[w["layer"] == "owner_portfolio"]
    stages = set(w["stage"])
    assert stages >= {"identity.splink_base", "identity.splink_feedback", "identity.registered_llc",
                      "deed.held_since", "deed.linked_successor"}
    by = w.groupby("stage").size()
    assert by["identity.splink_base"] > by["identity.splink_feedback"] > 0           # weak evidence is the minority

    # a feedback step cites a cluster whose accepted shared-company merge is a decision event
    fb = w[w["stage"] == "identity.splink_feedback"].iloc[0]
    ev = t["decision_events"]
    merged = ev[(ev["cluster_id"] == fb["basis_id"]) & (ev["stage"] == "identity.splink_feedback")
                & (ev["outcome"] == "accepted")]
    assert len(merged), "a feedback step must be explained by an accepted feedback merge"

    # a deed step cites an evidence item that has both its nodes as members
    d = w[w["stage"] == "deed.linked_successor"].iloc[0]
    mem = t["evidence_members"]
    nodes = set(mem.loc[mem["evidence_id"] == d["basis_id"], "node_id"])
    assert {d["node_a"], d["node_b"]} <= nodes

    # a registered-LLC step cites a set whose members include both nodes, each with its source lot
    l = w[w["stage"] == "identity.registered_llc"].iloc[0]
    lm = t["link_set_members"]
    got = lm[lm["set_id"] == l["basis_id"]]
    assert {l["node_a"], l["node_b"]} <= set(got["node_id"]) and got["source_bbl"].notna().all()
    assert t["link_sets"].set_index("set_id").loc[l["basis_id"], "stage"] == "identity.registered_llc"
