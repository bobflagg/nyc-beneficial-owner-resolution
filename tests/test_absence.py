"""bbl_status: why a lot is not in a group, and the precedence among reasons (no database), then the dump."""
import pandas as pd

from bor import absence
from bor.release_schema import PRECEDENCE, REASON_CODES


def _ev(rows):
    cols = ["decision_id", "layer", "stage", "subject_type", "subject_id", "counterpart_type", "counterpart_id",
            "outcome", "reason_code", "rule", "rule_version", "score", "threshold", "cluster_id", "detail"]
    df = pd.DataFrame(rows, columns=cols[:10])
    for c in cols[10:]:
        df[c] = None
    df["rule_version"] = "t"
    return df[cols]


def _tables():
    """Lots L1..L11. L1, L2 are grouped; L3 is a co-op in that group; the rest are absent for different reasons."""
    lwc = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5, "L6": 6, "L9": 9, "L10": 10, "L11": 11}
    nobs = pd.DataFrame({"node_id": list(lwc.values()), "bbl": list(lwc)})
    matched = [1, 2, 3, 4, 6, 9, 10, 11]                               # node 5 matched no identity
    ncl = pd.DataFrame({"node_id": matched, "cluster_id": [f"C{n}" for n in matched]})
    nim = pd.DataFrame({"node_id": matched, "identity_id": [f"I{n}" for n in matched],
                        "bbl": [f"L{n}" for n in matched]})
    ic = pd.DataFrame({"identity_id": [f"I{n}" for n in matched], "cluster_id": [f"C{n}" for n in matched],
                       "base_cluster_id": [f"BC{n}" for n in matched]})
    gb = pd.DataFrame([("owner_portfolio", "OP-1", "L1", True), ("owner_portfolio", "OP-1", "L2", True),
                       ("owner_portfolio", "OP-1", "L3", False),
                       ("operational_network", "ON-1", "L1", True), ("operational_network", "ON-1", "L2", True),
                       ("operational_network", "ON-1", "L3", True)], columns=["layer", "group_id", "bbl", "rental"])
    ev = _ev([
        ("e1", "identity", "identity.splink_base", "identity", "I4", "identity", "I1", "rejected", "first_name_veto", "first_name_veto"),
        ("e2", "owner_portfolio", "owner_portfolio.footprint", "bbl", "L3", "group", "OP-1", "excluded", "coop_condo_excluded", "coop_condo_contact_rule"),
        ("e3", "owner_portfolio", "owner_portfolio.footprint", "group", "OP-9", None, None, "dropped", "coop_condo_dominated", "group_footprint_rule"),
        ("e4", "owner_portfolio", "owner_portfolio.footprint", "bbl", "L9", "group", "OP-9", "excluded", "coop_condo_dominated", "group_footprint_rule"),
        ("e5", "operational_network", "network.address", "address", "A1", None, None, "masked", "aggregator_address_masked", "aggregator_address_mask"),
        ("e6", "owner_portfolio", "deed.held_since", "deed_document", "X1", None, None, "excluded", "institutional_screen", "institutional_screen"),
    ])
    sup = pd.DataFrame([("e6", "document", "X1", "deed"), ("e6", "bbl", "L11", "parcel")],
                       columns=["decision_id", "support_type", "support_id", "role"])
    mask = pd.DataFrame({"address_id": ["A1"], "node_id": [10]})
    return {"node_observations": nobs, "node_cluster": ncl, "node_identity_matches": nim, "identity_clusters": ic,
            "group_bbls": gb, "decision_events": ev, "decision_support": sup, "masked_address_nodes": mask}


def _status(layer):
    universe = ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9", "L10", "L11"]
    t = absence.bbl_status_table(universe, registered=["L7"], T=_tables())
    t = t[t["layer"] == layer].set_index("bbl")
    return {b: (r["status"], None if pd.isna(r["reason_code"]) else r["reason_code"]) for b, r in t.iterrows()}


def test_owner_portfolio_statuses_and_primary_reasons():
    s = _status("owner_portfolio")
    assert s["L1"] == ("in_group", None) and s["L2"] == ("in_group", None)
    assert s["L3"] == ("excluded_from_footprint", "coop_condo_excluded")      # in the group, out of the rental footprint
    assert s["L4"] == ("not_in_group", "first_name_veto")                     # a gate blocked its link
    assert s["L5"] == ("not_in_group", "unmatched_node")                      # no identity to link on
    assert s["L6"] == ("not_in_group", "no_linkage")                          # nothing applied
    assert s["L7"] == ("not_in_group", "no_owner_contact")                    # registered, but no qualifying contact
    assert s["L8"] == ("not_in_group", "no_registration")                     # HPD has no record of it
    assert s["L9"] == ("not_in_group", "coop_condo_dominated")                # its group was dropped
    assert s["L11"] == ("not_in_group", "institutional_screen")               # its joint deed was screened out


def test_the_two_layers_differ_where_the_evidence_differs():
    n = _status("operational_network")
    assert n["L3"] == ("in_group", None)                                      # the network has no co-op filter
    assert n["L10"] == ("not_in_group", "aggregator_address_masked")          # the network masks aggregator addresses
    assert n["L5"] == ("not_in_group", "no_linkage")                          # an unmatched identity is not a network gap
    assert n["L9"] == ("not_in_group", "no_linkage") and n["L11"] == ("not_in_group", "no_linkage")   # owner-portfolio rules
    assert n["L4"] == ("not_in_group", "first_name_veto")                     # identity-layer gates bear on both
    o = _status("owner_portfolio")
    assert o["L10"] == ("not_in_group", "no_linkage")                         # the network's mask does not apply here


def test_the_earliest_stage_wins_when_several_reasons_apply():
    t = _tables()
    # L5 is unmatched (outside method input) and also named by a veto event (below an eligibility rule)
    t["decision_events"] = pd.concat([t["decision_events"], _ev([
        ("e7", "owner_portfolio", "identity.splink_base", "bbl", "L5", None, None, "rejected", "first_name_veto", "first_name_veto")])])
    s = absence.bbl_status_table(["L5"], [], t).set_index(["layer", "bbl"]).loc[("owner_portfolio", "L5")]
    assert s["reason_code"] == "unmatched_node" and s["top_level_reason"] == "outside_method_input"
    # and a policy reason beats an eligibility reason
    t["decision_events"] = pd.concat([t["decision_events"], _ev([
        ("e8", "owner_portfolio", "owner_portfolio.footprint", "bbl", "L4", None, None, "excluded", "coop_condo_dominated", "group_footprint_rule")])])
    s = absence.bbl_status_table(["L4"], [], t).set_index(["layer", "bbl"]).loc[("owner_portfolio", "L4")]
    assert s["reason_code"] == "coop_condo_dominated"                           # excluded_by_policy outranks first_name_veto


def test_reasons_are_ordered_by_the_documented_precedence():
    order = sorted(REASON_CODES, key=lambda c: absence.RANK[c])
    tops = [REASON_CODES[c][0] for c in order]
    assert [PRECEDENCE.index(t) for t in tops] == sorted(PRECEDENCE.index(t) for t in tops)
    assert order[0] == "no_registration" and order[-1] == "pair_below_threshold"


def test_every_row_has_a_consistent_top_level_reason_and_group():
    universe = ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9", "L10", "L11"]
    t = absence.bbl_status_table(universe, ["L7"], _tables())
    assert not t.duplicated(["layer", "bbl"]).any() and set(t["layer"]) == set(absence.LAYERS)
    inn = t["status"] == "in_group"
    assert t.loc[inn, "group_id"].notna().all() and t.loc[inn, "reason_code"].isna().all()
    out = t["status"] == "not_in_group"
    assert t.loc[out, "group_id"].isna().all() and t.loc[out, "reason_code"].notna().all()
    top = t.loc[t["reason_code"].notna(), "reason_code"].map(lambda c: REASON_CODES[c][0])
    assert (top == t.loc[t["reason_code"].notna(), "top_level_reason"]).all()


def test_the_validator_agrees_with_the_summary_and_rejects_a_lower_reason():
    from bor.release_validate import _inv_bbl_status
    T = _tables()
    universe = ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9", "L10", "L11"]
    T["bbl_status"] = absence.bbl_status_table(universe, ["L7"], T)
    assert _inv_bbl_status(T) == []
    bad = T["bbl_status"].copy()
    bad.loc[(bad["layer"] == "owner_portfolio") & (bad["bbl"] == "L4"), ["reason_code", "top_level_reason"]] = [
        "no_linkage", "no_qualifying_linkage"]
    T["bbl_status"] = bad
    assert any(v.check == "precedence" for v in _inv_bbl_status(T))


def test_events_bear_on_lots_by_the_shared_rule():
    r = absence.lot_event_ranks(_tables())
    by = r.groupby("decision_id")["bbl"].apply(set).to_dict()
    assert by["e1"] == {"L4", "L1"}                         # an identity pair bears on both ends' lots
    assert by["e5"] == {"L10"} and by["e6"] == {"L11"}      # a masked address -> its nodes' lots; a deed -> its parcels
    layers = r[r["decision_id"] == "e1"]["layer"]
    assert set(layers) == set(absence.LAYERS)                # identity-layer events bear on both layers


# --- the reference dump: a whole release (needs the database) ----------------------------------

def _release(release_build):
    from bor.release_validate import read_release
    out, _ = release_build
    return read_release(str(out))[0]


def test_every_pluto_lot_has_a_status_in_both_layers(pg, release_build):
    t = _release(release_build)
    s = t["bbl_status"]
    cur = pg.cursor()
    cur.execute("SELECT DISTINCT trim(bbl) FROM pluto_latest WHERE bbl IS NOT NULL")
    pluto = {r[0] for r in cur.fetchall()}
    assert not s.duplicated(["layer", "bbl"]).any()
    for layer in absence.LAYERS:
        assert pluto <= set(s.loc[s["layer"] == layer, "bbl"]), layer
    # the lots reported in a group are exactly the groups' rental lots
    gb = t["group_bbls"]
    for layer in absence.LAYERS:
        want = set(gb.loc[(gb["layer"] == layer) & (gb["rental"] == "True"), "bbl"])
        got = set(s.loc[(s["layer"] == layer) & (s["status"] == "in_group"), "bbl"])
        assert got == want, layer
        left_out = set(gb.loc[(gb["layer"] == layer) & (gb["rental"] == "False"), "bbl"])
        assert left_out == set(s.loc[(s["layer"] == layer) & (s["status"] == "excluded_from_footprint"), "bbl"])


def test_the_dump_shows_every_kind_of_absence(release_build):
    t = _release(release_build)
    s = t["bbl_status"]
    op = s[s["layer"] == "owner_portfolio"]
    seen = set(op["reason_code"].dropna())
    assert {"no_registration", "no_owner_contact", "unmatched_node", "no_linkage", "coop_condo_excluded",
            "coop_condo_dominated"} <= seen, seen
    assert seen & {"first_name_veto", "common_name_veto", "deed_not_latest", "successor_not_shell",
                   "successor_transfer_not_nominal", "institutional_screen"}      # gates leave reasons too
    # most lots are simply not HPD-registered: outside source coverage
    assert (op["reason_code"] == "no_registration").sum() > (op["status"] == "in_group").sum()


def test_a_gate_reason_always_has_an_event_that_says_so(release_build):
    t = _release(release_build)
    s = t["bbl_status"]
    ranks = absence.lot_event_ranks(t)
    ranks["reason"] = ranks["score"].map(absence._CODE_OF)
    events_by_lot = ranks.groupby(["layer", "bbl"])["reason"].agg(set)
    from_events = s[s["reason_code"].isin(
        [c for c, (top, _) in REASON_CODES.items() if top in ("excluded_by_policy", "below_eligibility_rule")])]
    keyed = events_by_lot.reindex(pd.MultiIndex.from_frame(from_events[["layer", "bbl"]]))
    assert all(code in reasons for code, reasons in zip(from_events["reason_code"], keyed)
               if isinstance(reasons, set)) and keyed.notna().all()


def test_the_group_level_policy_events_account_for_every_dropped_and_left_out_lot(release_build):
    t = _release(release_build)
    ev = t["decision_events"]
    dropped = ev[(ev["outcome"] == "dropped") & (ev["reason_code"] == "coop_condo_dominated")]
    assert len(dropped) > 0 and not set(dropped["subject_id"]) & set(t["groups"]["group_id"])    # never published
    s = t["bbl_status"]
    op = s[s["layer"] == "owner_portfolio"]
    dropped_lots = ev[(ev["subject_type"] == "bbl") & (ev["reason_code"] == "coop_condo_dominated")]
    # a dropped group's lot is not in any group, and its reason is the co-op rule unless something that
    # removes a lot earlier (no registration, no owner contact, an unmatched node) also applies
    lots = op.set_index("bbl").loc[sorted(set(dropped_lots["subject_id"]))]
    assert (lots["status"] == "not_in_group").all()
    here = absence.RANK["coop_condo_dominated"]
    assert all(absence.RANK[c] <= here for c in lots["reason_code"])
    left_out = ev[ev["reason_code"] == "coop_condo_excluded"]
    assert set(left_out["subject_id"]) == set(op.loc[op["status"] == "excluded_from_footprint", "bbl"])
