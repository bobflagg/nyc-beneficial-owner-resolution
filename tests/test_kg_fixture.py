"""The approval gate (docs/kg-handoff-plan-v2.md, section 7), as tests, with no database.

A KG consumer holding one frozen release can: trace two grouped lots to exact source observations;
name each linkage stage a path needs; explain a cross-community path and an absence; display a
published metric directly; and verify the shared run and snapshot.

Two frozen fixtures, each a complete release that loads on its own:

* ``synthetic_release`` — made-up lots (every BBL starts with 9) that exercise every table and every
  case: a transitive feedback bridge, a deed mixing held and transferred parcels, a hub-capped node
  with another valid link, a dropped group, an ambiguous contact mapping, a component split across
  Louvain communities, a deed bridging two resolved owners, link sets, and each absence reason;
* ``citadel_excerpt`` — real rows: the Citadel deed veil-pierce, Owner Portfolio OP-67966, cut from a
  full build of the reference dump (``bor.excerpt``).
"""
import json
import os
import shutil

import pandas as pd
import pytest

from bor import explain as ex
from bor.release_schema import REASON_CODES, STAGES, TABLES
from bor.release_validate import read_release, validate_release

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
SYN, CIT = os.path.join(FIX, "synthetic_release"), os.path.join(FIX, "citadel_excerpt")
OP, ON = "owner_portfolio", "operational_network"
FACTS = {"no_registration", "no_owner_contact", "unmatched_node", "no_linkage"}   # absences with no event behind them


@pytest.fixture(scope="module")
def syn():
    return ex.Release.from_dir(SYN)


@pytest.fixture(scope="module")
def cit():
    return ex.Release.from_dir(CIT)


@pytest.fixture(scope="module", params=[SYN, CIT], ids=["synthetic", "citadel"])
def rel(request):
    return ex.Release.from_dir(request.param)


# --- loading, and the shared run and snapshot ---------------------------------------------------------

def test_a_consumer_loads_each_fixture_without_postgres_and_it_satisfies_the_contract():
    for path in (SYN, CIT):
        tables, manifest = read_release(path)
        assert validate_release(tables, manifest, path=path) == []
        assert set(tables) <= set(TABLES) and len(tables) >= 20


def test_one_run_and_snapshot_names_every_assertion(rel):
    m, run = rel.manifest, rel.manifest["run_id"]
    assert m["snapshot_id"] and m["pluto_snapshot_id"] and set(m["source_tables"]) >= {"hpd_contacts", "real_property_master"}
    for name in ("groups", "group_members", "group_witness"):
        assert rel.t[name]["assertion_key"].str.startswith(run + "/").all(), name
    # the KG's link id: one per (layer, lot), unique across the release
    g, gb = rel.t["groups"], rel.t["group_bbls"]
    link = gb.merge(g[["layer", "group_id", "assertion_key"]], on=["layer", "group_id"])
    ids = link["assertion_key"] + "#" + link["bbl"]
    assert ids.is_unique and len(ids) == len(gb)


@pytest.mark.parametrize("path", [SYN, CIT], ids=["synthetic", "citadel"])
def test_a_changed_file_or_run_is_detected(path, tmp_path):
    work = tmp_path / "copy"
    shutil.copytree(path, work)
    with open(work / "groups.csv", "a") as f:
        f.write("\n")
    tables, manifest = read_release(str(work))
    assert ("manifest", "checksum") in {(v.table, v.check) for v in validate_release(tables, manifest, path=str(work))}
    # tables from one run under another run's manifest
    tables, manifest = read_release(path)
    manifest["run_id"] = "some-other-run"
    assert ("manifest", "run_id") in {(v.table, v.check) for v in validate_release(tables, manifest)}


def test_the_synthetic_release_cannot_be_taken_for_a_real_one(syn):
    assert syn.manifest["synthetic"] is True and syn.manifest["run_id"].startswith("synthetic")
    assert syn.t["node_observations"]["bbl"].str.startswith("9").all()
    assert syn.t["bbl_status"]["bbl"].str.startswith("9").all()


def test_an_excerpt_says_it_is_one_and_whose(cit):
    e = cit.manifest["excerpt"]
    assert e["of_run_id"] == cit.manifest["run_id"] and e["seed_groups"] == ["OP-67966"]
    assert {"network_edges", "network_membership", "split_attempts"} <= set(e["tables_omitted"])
    src = cit.manifest["source_tables"]["hpd_contacts"]          # the parent's source fingerprint, not a placeholder
    assert "synthetic" not in cit.manifest and src["row_count"] > 100_000 and len(src["fingerprint"]) > 8


# --- 1. trace grouped lots to exact observations ------------------------------------------------------

def test_every_grouped_lot_traces_to_exact_hpd_observations(rel):
    nobs, obs = rel.t["node_observations"], rel.t["observations"].set_index("observation_id")
    alt = rel.t.get("node_observation_alternatives")
    grouped = set(rel.t["group_members"]["node_id"].astype(str))
    for r in nobs[nobs["node_id"].astype(str).isin(grouped)].itertuples():
        if r.ambiguous == "True":
            cands = alt[(alt["node_id"] == r.node_id) & (alt["bbl"] == r.bbl)]["observation_id"]
            assert len(cands) == int(r.n_candidates) and set(cands) <= set(obs.index)
        else:
            o = obs.loc[r.selected_observation_id]
            assert o["registration_id"] == r.registration_id          # the exact HPD registration and contact
            assert r.selected_observation_id == f"{o['registration_id']}:{o['registration_contact_id']}:{o['k']}"


def test_the_transitive_bridge_is_traced_to_contacts_without_inventing_a_score(syn):
    """Lots 1 and 3 are in one Owner Portfolio, though their people were never compared: the path runs
    through a scored match and a shared company, and cites exactly the company's contacts."""
    e = ex.explain_pair(syn, "9000100001", "9000100003")
    assert e.answer.startswith("Yes: both are in Owner Portfolio OP-9001") and len(e.steps) == 2
    assert [s["stage"] for s in e.steps] == ["identity.splink_base", "identity.splink_feedback"]
    nobs = syn.t["node_observations"].set_index("bbl")
    corp = [o for o in syn.t["observations"]["observation_id"] if o.endswith("01:0")]
    assert len(corp) == 2
    assert all(c in " ".join(e.steps[1]["evidence"]) for c in corp) and "no direct score" in " ".join(e.steps[1]["evidence"])
    # nothing in the release scores the first and third people against each other
    ev = syn.t["decision_events"]
    people = set(syn.t["node_identity_matches"].set_index("node_id").loc[["9001"], "identity_id"]), \
        set(syn.t["node_identity_matches"].set_index("node_id").loc[["9003"], "identity_id"])
    pairs = ev[ev["subject_id"].isin(people[0]) & ev["counterpart_id"].isin(people[1])]
    assert pairs.empty
    assert nobs.loc["9000100001", "selected_observation_id"] and nobs.loc["9000100003", "selected_observation_id"]


def test_citadel_lots_trace_to_the_2008_deed_and_each_2015_re_titling(cit):
    members = cit.t["evidence_members"]
    assert len(members) == 15 and set(members["original_document_id"]) == {"2008072300342001"}
    assert set(members["role"]) == {"transferred_onward"} and set(members["latest_amount"].astype(float)) == {0.0}
    assert members["latest_document_id"].nunique() == 12                  # twelve single-purpose LLCs' deeds
    e = ex.explain_pair(cit, "3012590047", "3052110017")
    assert e.answer.startswith("Yes: both are in Owner Portfolio OP-67966")
    assert e.weakest and "deed.linked_successor" in e.weakest[0]
    assert "ACRIS deed 2008072300342001" in " ".join(e.steps[0]["evidence"])
    assert any("2015050400848009 for $0" in x for x in e.steps[0]["evidence"])


# --- 2. name each linkage stage a path needs ------------------------------------------------------------

def test_every_group_names_its_stages_and_every_path_step_cites_evidence(rel):
    w, g = rel.t["group_witness"], rel.t["groups"]
    for r in g.itertuples():
        e = ex.explain_group(rel, r.group_id)
        stages = w[(w["layer"] == r.layer) & (w["group_id"] == r.group_id)]["stage"].value_counts().to_dict()
        assert e.data["stages"] == stages and set(stages) <= set(STAGES)
        nodes = e.data["nodes"]
        if len(nodes) > 1:
            a, b = rel.lots_of(nodes[0])[0], rel.lots_of(nodes[-1])[0]
            p = ex.explain_pair(rel, a, b, r.layer)
            assert p.answer.startswith("Yes") and p.steps and all(s["evidence"] for s in p.steps), (r.group_id, p.render())
            assert set(p.weakest) <= {f"{k} ({v})" for k, v in ex.WEAK_STAGES.items()}


def test_the_weak_stage_a_path_needs_is_named_and_only_then(syn):
    assert ex.explain_pair(syn, "9000100001", "9000100002").weakest == []
    assert "identity.splink_feedback" in ex.explain_pair(syn, "9000100001", "9000100003").weakest[0]
    deeds = ex.explain_pair(syn, "9000200001", "9000200003")
    assert "deed.linked_successor" in deeds.weakest[0]
    bridged = ex.explain_pair(syn, "9000700001", "9000700004")
    assert [s["stage"] for s in bridged.steps] == ["identity.splink_base", "deed.held_since", "identity.splink_base"]
    assert bridged.weakest == []


def test_a_deed_that_mixes_held_and_transferred_parcels_says_which_is_which(syn):
    m = syn.t["evidence_members"]
    m = m[m["evidence_id"] == "DV9000001"]
    assert m.groupby("role").size().to_dict() == {"held_under_joint_deed": 2, "transferred_onward": 2}
    assert syn.t["evidence_items"].set_index("evidence_id").loc["DV9000001", "stage"] == "deed.linked_successor"
    text = " ".join(ex.explain_pair(syn, "9000200001", "9000200003").steps[1]["evidence"])
    assert "joint deed is still its latest" in text and "conveyed on by deed 2999060100002001 for $0" in text
    # the fifth parcel was rejected: the onward deed was not nominal
    rej = ex.explain_lot(syn, "9000200005", OP)
    assert "successor_transfer_not_nominal" in rej.answer and "$3,200,000" in " ".join(rej.details)


def test_registered_company_and_curated_links_say_where_they_come_from(syn):
    llc = ex.explain_pair(syn, "9000800001", "9000800002")
    assert [s["stage"] for s in llc.steps] == ["identity.registered_llc"]
    assert "Link set LG9000001" in llc.steps[0]["evidence"][0] and any("9000800001" in x for x in llc.steps[0]["evidence"])
    curated = ex.explain_pair(syn, "9000800003", "9000800004")
    assert [s["stage"] for s in curated.steps] == ["identity.curated"] and "Link set CG9000001" in curated.steps[0]["evidence"][0]


# --- 3. a cross-community path -----------------------------------------------------------------------------

def test_two_lots_in_different_networks_have_a_path_with_the_boundary_marked(syn):
    e = ex.explain_pair(syn, "9000600003", "9000600004", ON)
    assert e.answer == "No: 9000600003 is in ON-9060 and 9000600004 is in ON-9063."
    line = " ".join(e.details)
    assert "one original component (NC-1)" in line and "1 of which cross a network boundary (NE9000004)" in line
    # a consumer without explain() finds the same from the tables
    mem, edges = syn.t["network_membership"], syn.t["network_edges"]
    a, b = mem.set_index("node_id").loc["9062"], mem.set_index("node_id").loc["9063"]
    assert a["component_id"] == b["component_id"] and a["operational_network_id"] != b["operational_network_id"]
    assert edges[edges["crosses_networks"] == "True"]["edge_id"].tolist() == ["NE9000004"]
    assert syn.t["split_attempts"].iloc[0][["component_id", "outcome", "communities"]].tolist() == ["NC-1", "split", "2"]
    assert set(syn.t["groups"].query("layer == @ON")["split"]) == {"louvain"}


def test_a_lot_cut_off_by_a_masked_hub_address_is_not_a_stray(syn):
    e = ex.explain_lot(syn, "9000600007", ON)
    assert "aggregator_address_masked" in e.answer and "excluded by policy" in e.answer
    assert any("degree 4" in d and "threshold 3" in d for d in e.details)
    m = syn.t["masked_addresses"].iloc[0]
    assert int(m["degree"]) == len(syn.t["masked_address_nodes"]) > int(m["threshold"])


def test_both_layers_can_group_the_same_lots_differently(syn):
    """9060-9061 are one Owner Portfolio (one person) and sit in one Operational Network (with 9062)."""
    assert ex.explain_lot(syn, "9000600001").data[OP]["group_id"] == "OP-9060"
    assert ex.explain_lot(syn, "9000600001").data[ON]["group_id"] == "ON-9060"
    assert ex.explain_lot(syn, "9000600003").data[OP]["group_id"] is None
    assert ex.explain_lot(syn, "9000600003").data[ON]["group_id"] == "ON-9060"


# --- 4. an absence ------------------------------------------------------------------------------------------

def test_every_reason_is_explained_and_every_event_reason_cites_an_event(rel):
    s, de = rel.t["bbl_status"], rel.t["decision_events"]
    for r in s[s["status"] == "not_in_group"].itertuples():
        e = ex.explain_lot(rel, r.bbl, r.layer)
        assert r.reason_code in e.answer and REASON_CODES[r.reason_code][0].replace("_", " ") in e.answer
        if r.reason_code not in FACTS:
            cited = [d for d in e.details if d.startswith(f"{ex.LAYER_NAME[r.layer]}: event ")]
            assert cited, (r.bbl, r.layer, r.reason_code)
            assert all(d.split("event ")[1].split(":")[0] in set(de["decision_id"]) for d in cited)


def test_all_five_top_level_reasons_appear_among_the_synthetic_absences(syn):
    s = syn.t["bbl_status"]
    assert set(s["top_level_reason"].dropna()) == {"outside_source_coverage", "outside_method_input", "excluded_by_policy",
                                                  "below_eligibility_rule", "no_qualifying_linkage"}
    row = lambda bbl, layer=OP: s[(s["bbl"] == bbl) & (s["layer"] == layer)].iloc[0]["reason_code"]
    assert row("9009900001") == "no_registration" and row("9009900002") == "no_owner_contact"
    assert row("9000900001") == "unmatched_node" and row("9000900002") == "no_linkage"


def test_a_primary_reason_follows_precedence_and_the_others_are_still_listed(syn):
    """Lot 4 was blocked by the first-name veto and its company bridge refused as not rare: both are
    'below an eligibility rule'; the earlier code in the vocabulary is primary."""
    e = ex.explain_lot(syn, "9000100004", OP)
    assert "first_name_veto" in e.answer and any("shared_company_name_not_rare" in d for d in e.details)


def test_a_dropped_group_and_a_footprint_exclusion_are_different_things(syn):
    dropped, coop = ex.explain_lot(syn, "9000100006", OP), ex.explain_lot(syn, "9000100005", OP)
    assert "coop_condo_dominated" in dropped.answer and "not in a group" in dropped.answer
    assert "member of OP-9001 but left out of its rental footprint" in coop.answer
    assert "OP-9006" not in set(syn.t["groups"]["group_id"])                  # a dropped group is not published
    assert (syn.t["decision_events"].query("outcome == 'dropped'")["subject_id"] == "OP-9006").all()


def test_a_deed_screen_explains_two_absent_lots(syn):
    for bbl in ("9000400001", "9000400002"):
        e = ex.explain_lot(syn, bbl, OP)
        assert "coop_condo_dominated" in e.answer
        assert any("coop_condo_deed_rule excluded deed_document 2999040400005001" in d for d in e.details)


def test_a_hub_capped_node_keeps_its_other_link_and_the_deed_names_why_it_did_not_link(syn):
    hub = ex.explain_lot(syn, "9000300001", OP)
    assert hub.data[OP]["group_id"] == "OP-9030"                              # held by its identity
    m = syn.t["evidence_members"].query("evidence_id == 'DV9000002'").set_index("bbl")
    assert m.loc["9000300001", "excluded_reason"] == "deed_hub_capped" and m["excluded_reason"].notna().sum() == 1
    pair = ex.explain_pair(syn, "9000300001", "9000300003")
    assert pair.answer == "No: 9000300001 is in OP-9030 and 9000300003 is in OP-9032."
    assert any("share ACRIS deed 2999020200003001" in d and "left out of every deed link" in d for d in pair.details)
    # the other two parcels on that deed are linked
    assert ex.explain_pair(syn, "9000300003", "9000300004").answer.startswith("Yes")


def test_an_ambiguous_contact_mapping_is_a_tie_the_release_shows_instead_of_hiding(syn):
    nobs = syn.t["node_observations"].set_index("node_id").loc["9050"]
    assert nobs["ambiguous"] == "True" and nobs["n_candidates"] == "2" and pd.isna(nobs["selected_observation_id"])
    alt = syn.t["node_observation_alternatives"]
    assert len(alt) == 2 and set(alt["observation_id"]) <= set(syn.t["observations"]["observation_id"])
    nc = syn.t["node_cluster"].set_index("node_id").loc["9050"]
    ca = syn.t["node_cluster_alternatives"].query("node_id == '9050'")
    assert nc["n_clusters"] == "2" and nc["tied"] == "True" and ca["selected"].tolist().count("True") == 1
    pair = ex.explain_pair(syn, "9000500001", "9000500003")
    assert "No:" in pair.answer and any("more than one reading" in d and "cannot say which is the owner" in d for d in pair.details)
    # the pair that was blocked by a gate, in contrast, says which gate
    blocked = ex.explain_pair(syn, "9000100003", "9000100004")
    assert any("first_name_veto rejected identity" in d and "score 0.9996" in d for d in blocked.details)


# --- 5. a published metric, as stored -----------------------------------------------------------------------------

def test_a_metric_is_displayed_as_published_and_an_unevaluated_one_says_why(syn):
    m = syn.t["method_metrics"]
    assert set(m["stage"]) <= set(STAGES) and (m["unit"] == "pair").all() and m["provisional"].eq("True").all()
    done = m[m["precision"].notna()].iloc[0]
    assert (float(done["precision"]), float(done["ci_lower"]), float(done["ci_upper"]), done["confidence_level"]) == (0.5, 0.25, 0.75, "0.95")
    assert float(done["ci_lower"]) <= float(done["precision"]) <= float(done["ci_upper"])
    assert "SYNTHETIC" in done["note"]                                         # not a measurement
    blank = m[m["precision"].isna()].iloc[0]
    assert blank["note"] and blank["adjudication_status"] == "none"
    assert not any("probab" in c for c in m.columns)                           # a precision, never a link probability


# --- a fixture is stable ------------------------------------------------------------------------------------------------

def test_the_synthetic_generator_reproduces_the_committed_fixture(tmp_path):
    """Regenerating gives byte-identical files (run `tests/fixtures/make_synthetic_release.py` after a
    contract change and commit the result)."""
    import subprocess
    import sys
    work = tmp_path / "gen"
    shutil.copytree(os.path.join(FIX), work)
    r = subprocess.run([sys.executable, str(work / "make_synthetic_release.py")], capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": os.path.join(os.path.dirname(__file__), "..", "src")})
    assert r.returncode == 0, r.stdout + r.stderr
    for f in sorted(os.listdir(SYN)):
        assert open(os.path.join(SYN, f), "rb").read() == open(work / "synthetic_release" / f, "rb").read(), f
    assert sorted(os.listdir(SYN)) == sorted(os.listdir(work / "synthetic_release"))


# --- the Citadel case in the Operational Network --------------------------------------------------------------------------

def test_citadel_is_one_owner_portfolio_and_no_operational_network_because_the_hub_office_is_masked(cit):
    g = cit.t["groups"].iloc[0]
    assert (g["group_id"], g["composition"], g["lot_count"]) == ("OP-67966", "deed_only", "20")
    assert len(cit.t["group_members"]) == 3 and set(cit.t["group_witness"]["stage"]) == {"deed.linked_successor"}
    s = cit.t["bbl_status"]
    assert (s.query("layer == @OP")["status"] == "in_group").all() and len(s.query("layer == @OP")) == 20
    on = s.query("layer == @ON")
    assert set(on["reason_code"]) == {"aggregator_address_masked"} and set(on["status"]) == {"not_in_group"}
    e = ex.explain_lot(cit, "3012590047", ON)
    assert "aggregator_address_masked" in e.answer and any("degree 33" in d and "threshold 25" in d for d in e.details)
    # an excerpt lists only the nodes it kept; the hub's degree is the full run's
    assert cit.t["masked_addresses"].iloc[0]["degree"] == "33" and len(cit.t["masked_address_nodes"]) == 3


def test_citadel_does_not_overstate_what_it_found(cit):
    e = ex.explain_group(cit, "OP-67966")
    text = e.render()
    assert "a lead, not a determination of ownership" in text and "provisional" in text
    json.dumps(e.to_dict())                                                    # structured form is serializable
