"""The release contract: schema sanity, the mini fixture, and that the validator catches breakage."""
import copy
import os

import pandas as pd
import pytest

from bor.release_schema import (MANIFEST_REQUIRED, PRECEDENCE, REASON_CODES, RULES, STAGES, TABLES,
                                TOP_LEVEL_REASONS)
from bor.release_validate import read_release, validate_release

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "mini_release")


def _load():
    tables, manifest = read_release(FIXTURE)
    return {k: v.copy() for k, v in tables.items()}, copy.deepcopy(manifest)


def _errors(tables, manifest=None, **kw):
    return [v for v in validate_release(tables, manifest, check_manifest_too=manifest is not None, **kw)
            if v.severity == "error"]


def _checks(tables, manifest=None, **kw):
    return {(v.table, v.check) for v in _errors(tables, manifest, **kw)}


# --- schema sanity -----------------------------------------------------------------------------

def test_foreign_keys_and_keys_refer_to_real_columns():
    for t in TABLES.values():
        names = {c.name for c in t.columns}
        assert set(t.key) <= names, t.name
        for fk in t.fks:
            assert set(fk.cols) <= names, (t.name, fk)
            assert fk.table in TABLES, (t.name, fk)
            assert set(fk.ref_cols) <= {c.name for c in TABLES[fk.table].columns}, (t.name, fk)


def test_vocabularies_are_consistent():
    assert len(set(STAGES)) == len(STAGES)
    assert len(set(RULES)) == len(RULES)
    assert set(PRECEDENCE) == set(TOP_LEVEL_REASONS) and len(TOP_LEVEL_REASONS) == 5
    assert {top for top, _ in REASON_CODES.values()} == set(TOP_LEVEL_REASONS)   # all five are used
    # the codes that explain "the source has the record but the method did not use it"
    assert {c for c, (top, _) in REASON_CODES.items() if top == "outside_method_input"} == {
        "no_owner_contact", "not_latest_registration", "unmatched_node"}


def test_every_fixture_file_is_a_contract_table():
    tables, _ = read_release(FIXTURE)
    files = {f[:-4] for f in os.listdir(FIXTURE) if f.endswith(".csv")}
    assert files == set(tables) <= set(TABLES)


# --- the fixture -------------------------------------------------------------------------------

def test_fixture_satisfies_the_contract():
    tables, manifest = read_release(FIXTURE)
    found = validate_release(tables, manifest, path=FIXTURE)
    assert found == []


def test_fixture_explains_a_to_c_through_both_decisions():
    """Lots 1 and 3 are grouped though their identities were never compared: the witness path runs
    1-2 (a base decision) then 2-3 (a feedback merge), all on cluster C0000001."""
    t, _ = _load()
    w = t["group_witness"].sort_values("step")
    assert list(zip(w["node_a"], w["node_b"], w["stage"])) == [   # read_release leaves strings
        ("1", "2", "identity.splink_base"), ("2", "3", "identity.splink_feedback"),
        ("3", "5", "identity.splink_base")]
    ev = t["decision_events"]
    on_c = ev[ev["cluster_id"] == "C0000001"]
    assert set(on_c["stage"]) == {"identity.splink_base", "identity.splink_feedback"}
    # no event scores the first and third identities against each other
    pair = {"I0000001", "I0000003"}
    assert not any({a, b} == pair for a, b in zip(ev["subject_id"], ev["counterpart_id"]))
    # the feedback merge cites the shared company's exact contacts, with no names
    sup = t["decision_support"]
    assert set(sup.loc[sup["decision_id"] == "d2", "support_id"]) == {"101:10103:0", "103:10303:0"}


def test_fixture_explains_an_absence_by_a_gate_not_a_score():
    t, _ = _load()
    s = t["bbl_status"].set_index("bbl").loc["3000010004"]
    assert s["status"] == "not_in_group"
    assert (s["reason_code"], s["top_level_reason"]) == ("first_name_veto", "below_eligibility_rule")
    d3 = t["decision_events"].set_index("decision_id").loc["d3"]
    assert d3["outcome"] == "rejected" and d3["rule"] == "first_name_veto"
    assert float(d3["score"]) > float(d3["threshold"])           # blocked by the gate, not by the score


def test_coop_lot_in_a_group_and_a_dropped_group_have_different_codes_and_rules():
    t, _ = _load()
    s = t["bbl_status"].set_index("bbl")
    ev = t["decision_events"].set_index("decision_id")
    lot, dropped = s.loc["3000010005"], s.loc["3000010006"]
    assert (lot["status"], lot["reason_code"]) == ("excluded_from_footprint", "coop_condo_excluded")
    assert lot["group_id"] == "OP-1"                              # still a member of the published group
    assert (dropped["status"], dropped["reason_code"]) == ("not_in_group", "coop_condo_dominated")
    assert ev.loc["d5", "rule"] == "coop_condo_contact_rule" and ev.loc["d7", "rule"] == "group_footprint_rule"
    assert ev.loc["d7", "outcome"] == "dropped" and "OP-6" not in set(t["groups"]["group_id"])
    g = t["group_bbls"].set_index("bbl")
    assert g.loc["3000010005", "rental"] == "False"


# --- the validator catches breakage ------------------------------------------------------------

def test_clean_copy_has_no_errors():
    t, m = _load()
    assert _errors(t, m, path=FIXTURE) == []


def test_missing_column():
    t, _ = _load()
    t["groups"] = t["groups"].drop(columns="assertion_key")
    assert ("groups", "columns") in _checks(t)


def test_duplicate_key():
    t, _ = _load()
    t["node_observations"] = pd.concat([t["node_observations"]] * 2, ignore_index=True)
    assert ("node_observations", "key") in _checks(t)


def test_enum_violation():
    t, _ = _load()
    t["decision_events"].loc[0, "stage"] = "identity.made_up"
    assert ("decision_events", "enum") in _checks(t)


def test_broken_foreign_key():
    t, _ = _load()
    t["node_identity_matches"].loc[0, "identity_id"] = "ghost"
    assert ("node_identity_matches", "fk") in _checks(t)


def test_witness_cycle_and_disconnect():
    t, _ = _load()
    extra = t["group_witness"].iloc[[0]].copy()
    extra["step"], extra["node_a"], extra["node_b"] = 4, 1, 3
    extra["assertion_key"] = "mini-0001/owner_portfolio/OP-1/w4"
    cyc = dict(t)
    cyc["group_witness"] = pd.concat([t["group_witness"], extra], ignore_index=True)
    assert ("group_witness", "tree") in _checks(cyc)
    broken = dict(t)
    broken["group_witness"] = t["group_witness"].iloc[[0]]
    assert ("group_witness", "tree") in _checks(broken)


def test_accepted_event_with_reason_and_rejected_without():
    t, _ = _load()
    t["decision_events"].loc[0, "reason_code"] = "no_linkage"
    t["decision_events"].loc[2, "reason_code"] = pd.NA
    assert ("decision_events", "reason") in _checks(t)


def test_event_pointing_at_a_missing_identity():
    t, _ = _load()
    t["decision_events"].loc[0, "subject_id"] = "ident-zzz"
    assert ("decision_events", "reference") in _checks(t)


def test_ambiguous_row_must_not_carry_a_selection():
    t, _ = _load()
    t["node_observations"].loc[0, ["ambiguous", "n_candidates"]] = ["True", "2"]
    assert ("node_observations", "ambiguous") in _checks(t)


def test_reason_top_level_must_match():
    t, _ = _load()
    t["bbl_status"].loc[t["bbl_status"]["status"] == "not_in_group", "top_level_reason"] = "excluded_by_policy"
    assert ("bbl_status", "reason") in _checks(t)


def test_in_group_row_needs_a_group():
    t, _ = _load()
    t["bbl_status"].loc[0, "group_id"] = pd.NA
    assert ("bbl_status", "status") in _checks(t)


def test_group_counts_must_match_bbls():
    t, _ = _load()
    t["groups"].loc[0, "lot_count"] = "9"
    assert ("groups", "counts") in _checks(t)


def test_node_in_two_groups_is_a_key_violation():
    t, _ = _load()
    dup = t["group_members"].iloc[[0]].copy()
    dup["group_id"] = "OP-9"
    t["group_members"] = pd.concat([t["group_members"], dup], ignore_index=True)
    assert ("group_members", "key") in _checks(t)


def test_unevaluated_metric_needs_a_note():
    t, _ = _load()
    t["method_metrics"].loc[0, "note"] = pd.NA
    assert ("method_metrics", "null") in _checks(t)


def test_precision_must_sit_inside_its_interval():
    t, _ = _load()
    t["method_metrics"].loc[0, ["precision", "ci_lower", "ci_upper"]] = ["0.5", "0.6", "0.7"]
    assert ("method_metrics", "interval") in _checks(t)


def test_manifest_missing_field_and_bad_checksum():
    t, m = _load()
    bad = dict(m)
    bad.pop(MANIFEST_REQUIRED[1])
    assert ("manifest", "field") in _checks(t, bad)
    bad = copy.deepcopy(m)
    bad["output_checksums"]["groups.csv"] = "0" * 64
    assert ("manifest", "checksum") in _checks(t, bad, path=FIXTURE)


def test_unknown_artifact_kind():
    t, m = _load()
    m["artifacts"]["group_witness"] = "approximate"
    assert ("manifest", "artifacts") in _checks(t, m)


def test_parent_table_missing_is_an_error():
    t, _ = _load()
    del t["decision_events"]
    assert ("decision_support", "fk_parent_missing") in _checks(t)


# --- the implemented tables really match the contract ------------------------------------------

def test_lineage_output_satisfies_the_contract(pg, resolved):
    from bor.lineage import build_mapping
    tables, _ = build_mapping(pg, resolved)
    assert {n for n in tables} <= {n for n, t in TABLES.items() if t.status == "implemented"}
    assert _errors(tables) == []
    # ids are opaque: no md5 of a name and address leaves the release
    assert tables["identity_clusters"]["identity_id"].str.fullmatch(r"I\d{7}").all()
    assert tables["identity_clusters"]["cluster_id"].str.fullmatch(r"C\d{7}").all()
    assert tables["identity_clusters"]["base_cluster_id"].str.fullmatch(r"BC\d{7}").all()
    assert tables["observations"]["pair_variants"].max() >= 2          # repeated contact ids are flagged


# --- amendments from the KG review --------------------------------------------------------------

def test_rule_is_a_controlled_vocabulary():
    t, _ = _load()
    t["decision_events"].loc[0, "rule"] = "mystery-rule"
    assert ("decision_events", "enum") in _checks(t)


def test_policy_event_stage_must_be_a_known_stage():
    t, _ = _load()
    t["decision_events"].loc[t["decision_events"]["decision_id"] == "d5", "stage"] = "policy.footprint"
    assert ("decision_events", "enum") in _checks(t)


def test_primary_reason_must_be_the_highest_precedence_among_the_lots_events():
    t, _ = _load()
    # lot 4's events say first_name_veto (eligibility); calling it plain no_linkage ranks lower
    t["bbl_status"].loc[t["bbl_status"]["bbl"] == "3000010004", ["reason_code", "top_level_reason"]] = [
        "no_linkage", "no_qualifying_linkage"]
    assert ("bbl_status", "precedence") in _checks(t)


def test_a_higher_precedence_reason_than_the_events_is_allowed():
    t, _ = _load()
    t["bbl_status"].loc[t["bbl_status"]["bbl"] == "3000010004", ["reason_code", "top_level_reason"]] = [
        "unmatched_node", "outside_method_input"]
    assert ("bbl_status", "precedence") not in _checks(t)


def test_footprint_status_must_match_non_rental_lots():
    t, _ = _load()
    t["bbl_status"].loc[t["bbl_status"]["bbl"] == "3000010005", ["status"]] = "in_group"
    t["bbl_status"].loc[t["bbl_status"]["bbl"] == "3000010005", ["reason_code", "top_level_reason"]] = [pd.NA, pd.NA]
    assert ("bbl_status", "footprint") in _checks(t)


def test_a_dropped_group_must_not_be_published_and_a_published_one_must_not_be_dropped():
    t, _ = _load()
    t["decision_events"].loc[t["decision_events"]["decision_id"] == "d7", "subject_id"] = "OP-1"
    assert ("decision_events", "reference") in _checks(t)
    t, _ = _load()
    t["decision_events"].loc[t["decision_events"]["decision_id"] == "d7", "outcome"] = "excluded"
    assert ("decision_events", "reference") in _checks(t)


def test_a_bbl_belongs_to_exactly_one_node():
    t, _ = _load()
    dup = t["node_observations"].iloc[[0]].copy()
    dup["node_id"] = "99"
    t["node_observations"] = pd.concat([t["node_observations"], dup], ignore_index=True)
    assert ("node_observations", "bbl_once") in _checks(t)


def test_k_must_be_below_pair_variants():
    t, _ = _load()
    t["observations"].loc[0, "k"] = "1"
    assert ("observations", "k") in _checks(t)


def test_manifest_must_fingerprint_sources_and_name_the_deed_rule():
    t, m = _load()
    for field in ("snapshot_date", "snapshot_date_basis", "source_tables", "deed_selection_rule", "normalizer_versions"):
        assert field in MANIFEST_REQUIRED
    bad = copy.deepcopy(m)
    del bad["source_tables"]["hpd_contacts"]["fingerprint"]
    del bad["deed_selection_rule"]["version"]
    checks = _checks(t, bad)
    assert ("manifest", "source_tables") in checks and ("manifest", "deed_selection_rule") in checks


def test_counting_unit_is_lots():
    cols = {c.name for c in TABLES["groups"].columns}
    assert {"lot_count", "total_lot_count"} <= cols and not {"building_count", "total_building_count"} & cols


def test_group_id_prefix_must_match_the_layer():
    t, _ = _load()
    assert set(t["groups"]["group_id"].str[:3]) == {"OP-"}
    t["groups"].loc[0, "group_id"] = "ON-1"
    t["group_members"]["group_id"] = "ON-1"
    t["group_bbls"]["group_id"] = "ON-1"
    assert ("groups", "group_id_prefix") in _checks(t)
