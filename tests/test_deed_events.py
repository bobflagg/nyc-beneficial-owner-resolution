"""Deed gates, parcel outcomes and the evidence they produce (no database), then the reference dump."""
import json

import pandas as pd

from bor import deed_edges as de
from bor import deed_events as dv
from bor.release_validate import validate_release

NOMINAL, SALE = 0.0, 1_100_000.0


# --- the per-parcel outcome of the linked-successor guard ---------------------------------------

def _latest(**kw):
    """bbl -> (latest_doc, {grantor}, successor, docamount)"""
    return kw


def test_every_parcel_outcome_has_its_reason():
    G = {"ACME"}
    latest = {
        "held":    ("J", {"SELLER"}, "ACME", 10.0),                # the joint deed is still the latest
        "restr":   ("L1", {"ACME"}, "SHELL1LLC", NOMINAL),         # grantee restructured it, nominal
        "sold":    ("L2", {"STRANGER"}, "BUYER", SALE),            # conveyed on by someone else
        "bigsucc": ("L3", {"ACME"}, "BIGBUYER", NOMINAL),          # successor holds many buildings
        "market":  ("L4", {"ACME"}, "SHELL2LLC", SALE),            # successor is a shell, but a market sale
    }
    succ = {"SHELL1LLC": 1, "SHELL2LLC": 2, "BIGBUYER": 40}
    got = {b: (o, r) for b, o, r, *_ in
           de._parcel_outcomes("J", ["held", "restr", "sold", "bigsucc", "market", "nolatest"], G, latest, succ, 3)}
    assert got == {"held": ("held", None), "restr": ("restructured", None),
                   "sold": ("rejected", "deed_not_latest"), "bigsucc": ("rejected", "successor_not_shell"),
                   "market": ("rejected", "successor_transfer_not_nominal")}      # no latest deed: skipped


def test_a_missing_amount_is_not_nominal_so_the_parcel_is_rejected():
    latest = {"p": ("L", {"ACME"}, "SHELL", None)}
    out = de._parcel_outcomes("J", ["p"], {"ACME"}, latest, {"SHELL": 1}, 3)
    assert out[0][1:3] == ("rejected", "successor_transfer_not_nominal")


def test_retained_is_still_exactly_the_non_rejected_parcels():
    G = {"ACME"}
    latest = {"a": ("J", set(), "X", 0.0), "b": ("L", {"ACME"}, "S", 0.0), "c": ("L", {"OTHER"}, "S", 0.0)}
    assert de._retained("J", ["a", "b", "c"], G, latest, {"S": 1}, 3) == ["a", "b"]


def test_deed_level_gates():
    assert de._screen_reasons(3, 0.0, False, 25) == []
    assert de._screen_reasons(26, 0.0, False, 25) == ["deed_parcels_out_of_range"]
    assert de._screen_reasons(3, 0.0, True, 25) == ["institutional_screen"]
    assert de._screen_reasons(3, 0.5, False, 25) == []                          # exactly half passes
    assert de._screen_reasons(3, 0.51, False, 25) == ["coop_condo_dominated"]
    assert de._screen_reasons(30, 1.0, True, 25) == [
        "deed_parcels_out_of_range", "institutional_screen", "coop_condo_dominated"]


def test_the_candidate_queries_share_the_gates_predicates():
    d = None
    for sql in (de._held_candidates_sql(d), de._joint_candidates_sql(d)):
        assert de._PUBLIC_LIKE in sql and "coop AS" in sql and "CURRENT_DATE" not in sql
        assert f">= {de.MIN_PARCELS}" in sql
    assert de._LATEST_ORDER in de._held_candidates_sql(d)


# --- evidence ----------------------------------------------------------------------------------

def _trace():
    """Deed D1: lots 1,2 held; lot 3 transferred onward to a shell. Deed D2: lots 4,5 held, but node 9
    is a hub. Deed D3: lots 6,7 are in one node (links nothing). Gates dropped X1 (relevant) and X2."""
    parcels = pd.DataFrame([
        ("D1", "L1", "held", None, "D1", 5.0), ("D1", "L2", "held", None, "D1", 5.0),
        ("D1", "L3", "restructured", None, "T9", 0.0), ("D1", "L8", "rejected", "deed_not_latest", "T8", 700000.0),
        ("D1", "L9", "rejected", "successor_not_shell", "T7", 0.0),
        ("D3", "L6", "held", None, "D3", 1.0), ("D3", "L7", "rejected", "deed_not_latest", "T6", 5.0),
    ], columns=["doc", "bbl", "outcome", "reason", "latest_doc", "latest_amount"])
    bbl_nodes = {"L1": 1, "L2": 2, "L3": 3, "L4": 8, "L5": 9, "L6": 6, "L7": 6, "L8": 4, "L9": 5,
                 "X1a": 10, "X1b": 11}
    held = pd.DataFrame({"doc": ["D1", "D2", "D3"], "bbls": [["L1", "L2"], ["L4", "L5"], ["L6", "L7"]]})
    groups = {"D1": {1, 2, 3}, "D2": {8, 9}}
    screens_held = pd.DataFrame([
        ("held_since", "X1", "institutional_screen", "party_keywords", 2, ["X1a", "X1b"]),
        ("held_since", "X2", "deed_parcels_out_of_range", "parcel_count", 30, ["Z1", "Z2"])],   # no nodes
        columns=["path", "doc", "reason", "screen", "n_parcels", "bbls"])
    screens_joint = pd.DataFrame([("linked_successor", "X1", "coop_condo_dominated", "coop_condo", 2, ["X1a", "X1b"])],
                                 columns=screens_held.columns)
    return {"groups": groups, "bbl_nodes": bbl_nodes, "hubs": {9: 25}, "hub_cap": 20, "held": held,
            "parcels": parcels, "screens_held": screens_held, "screens_joint": screens_joint}


def test_a_mixed_deed_shows_each_parcels_role_and_latest_deed():
    items, members, rep = dv.evidence_tables(_trace(), {"D1": 5.0, "D2": 9.0, "D3": 1.0}, "bor-test")
    d1 = items[items["document_id"] == "D1"].iloc[0]
    assert d1["stage"] == "deed.linked_successor" and d1["parcel_count"] == 3     # one member depends on the guard
    m = members[members["evidence_id"] == d1["evidence_id"]].set_index("bbl")
    assert m.loc["L1", "role"] == "held_under_joint_deed" and m.loc["L1", "latest_document_id"] == "D1"
    assert m.loc["L3", "role"] == "transferred_onward" and m.loc["L3", "latest_document_id"] == "T9"
    assert m.loc["L3", "latest_amount"] == 0.0 and (m["original_document_id"] == "D1").all()
    assert "L8" not in m.index and "L9" not in m.index                              # rejected parcels are not evidence
    d2 = items[items["document_id"] == "D2"].iloc[0]
    assert d2["stage"] == "deed.held_since"                                         # nothing depends on the guard


def test_hub_members_are_kept_but_marked():
    _, members, _ = dv.evidence_tables(_trace(), {"D2": 9.0}, "bor-test")
    m = members[members["bbl"] == "L5"].iloc[0]
    assert m["excluded_reason"] == "deed_hub_capped" and pd.isna(members[members["bbl"] == "L4"].iloc[0]["excluded_reason"])


def test_a_deed_that_links_nothing_is_not_evidence():
    items, _, _ = dv.evidence_tables(_trace(), {}, "bor-test")
    assert set(items["document_id"]) == {"D1", "D2"}


# --- decisions ----------------------------------------------------------------------------------

def test_only_decisions_that_could_have_changed_a_link_are_events():
    events, support = dv.event_tables(_trace(), "bor-test")
    by = events.groupby(["stage", "reason_code"]).size().to_dict()
    assert by == {("deed.group", "deed_hub_capped"): 1,
                  ("deed.held_since", "institutional_screen"): 1,              # X1 reaches two nodes
                  ("deed.linked_successor", "coop_condo_dominated"): 1,
                  ("deed.linked_successor", "deed_not_latest"): 1,             # D1/L8; D3/L7 is in a one-node deed
                  ("deed.linked_successor", "successor_not_shell"): 1}
    assert not (events["subject_id"] == "X2").any()                           # no nodes: not relevant
    assert not (events["subject_id"] == "L7").any()


def test_events_carry_the_right_rule_outcome_and_documents():
    events, support = dv.event_tables(_trace(), "bor-test")
    e = events.set_index("reason_code")
    assert (e.loc["institutional_screen", "rule"], e.loc["institutional_screen", "outcome"]) == ("institutional_screen", "excluded")
    assert (e.loc["coop_condo_dominated", "rule"]) == "coop_condo_deed_rule"
    assert e.loc["deed_not_latest", "rule"] == "deed_latest_rule" and e.loc["successor_not_shell", "rule"] == "deed_successor_guard"
    assert e.loc["deed_not_latest", "counterpart_id"] == "D1" and e.loc["deed_not_latest", "subject_type"] == "parcel"
    assert (events["layer"] == "owner_portfolio").all() and events["decision_id"].is_unique
    hub = e.loc["deed_hub_capped"]
    assert json.loads(hub["detail"]) == {"deeds": 25, "hub_cap": 20}
    d = events.set_index("decision_id")
    docs = support.groupby("decision_id")["support_id"].apply(set)
    nl = e.loc["deed_not_latest", "decision_id"]
    assert docs[nl] == {"D1", "T8"} and set(support.loc[support["decision_id"] == nl, "role"]) == {"joint_deed", "latest_deed"}


def test_event_numbering_is_deterministic():
    a, _ = dv.event_tables(_trace(), "bor-test")
    b, _ = dv.event_tables(_trace(), "bor-test")
    pd.testing.assert_frame_equal(a, b)


def test_the_assembled_deed_layer_satisfies_the_contract():
    t = _trace()
    items, members, _ = dv.evidence_tables(t, {"D1": 5.0, "D2": 9.0, "D3": 1.0}, "bor-test")
    events, support = dv.event_tables(t, "bor-test")
    nodes = sorted(set(t["bbl_nodes"].values()))
    node_obs = pd.DataFrame([(n, b) for b, n in t["bbl_nodes"].items()], columns=["node_id", "bbl"])
    node_obs["registration_id"], node_obs["n_candidates"], node_obs["selected_observation_id"] = 1, 0, None
    node_obs["ambiguous"] = False
    observations = pd.DataFrame(columns=["observation_id", "registration_id", "registration_contact_id", "k",
                                         "pair_variants"])
    tables = {"observations": observations, "node_observations": node_obs, "evidence_items": items, "evidence_members": members,
              "decision_events": events, "decision_support": support}
    errors = [v for v in validate_release(tables, check_manifest_too=False) if v.severity == "error"]
    assert errors == [], errors


# --- the reference dump (needs the database) ----------------------------------------------------

def _traced(pg):
    trace = {}
    edges = de.deed_edges(pg, as_of=pd.Timestamp("2026-10-21").date(), trace=trace)
    return edges, trace


def test_tracing_changes_no_edge_and_reproduces_the_sql(pg):
    plain = de.deed_edges(pg, as_of=pd.Timestamp("2026-10-21").date())
    edges, trace = _traced(pg)
    pd.testing.assert_frame_equal(plain.reset_index(drop=True), edges.reset_index(drop=True))
    assert trace["held_consistent"] and trace["joint_consistent"]     # the candidate queries agree with the SQL
    assert len(trace["screens_held"]) and len(trace["screens_joint"]) and len(trace["parcels"])


def test_the_deed_layer_on_the_reference_dump(pg):
    import bor
    edges, trace = _traced(pg)
    tables, rep = dv.deed_tables(pg, trace, f"bor-{bor.__version__}")
    items, members, events = tables["evidence_items"], tables["evidence_members"], tables["deed_events"]
    assert len(items) == len(trace["groups"])
    assert abs(len(edges) - 947) <= 30 and abs(len(items) - 839) <= 30          # measured on the reference dump
    assert abs(int((items["stage"] == "deed.linked_successor").sum()) - 77) <= 10
    # a mixed deed: some parcels held under the joint deed, others transferred onward, each with its own latest deed
    roles = members.groupby("evidence_id")["role"].agg(set)
    mixed = roles[roles.map(lambda r: r == {"held_under_joint_deed", "transferred_onward"})]
    assert len(mixed), "expected deeds that mix held and transferred parcels"
    m = members[members["evidence_id"] == mixed.index[0]]
    held, moved = m[m["role"] == "held_under_joint_deed"], m[m["role"] == "transferred_onward"]
    assert (held["latest_document_id"] == held["original_document_id"]).all()
    assert (moved["latest_document_id"] != moved["original_document_id"]).all()
    assert items.set_index("evidence_id").loc[mixed.index[0], "stage"] == "deed.linked_successor"
    # the nominal gate and the hub cap leave events
    reasons = set(events["reason_code"])
    assert {"successor_transfer_not_nominal", "deed_not_latest", "successor_not_shell"} <= reasons
    assert rep["held_trace_matches_sql"] and rep["joint_trace_matches_sql"]
    # the hub cap (20 deeds) never triggers on this dump: the busiest node is on 19. Unit tests cover it.
    hubs = set(trace["hubs"])
    assert hubs == set() and members["excluded_reason"].isna().all()
