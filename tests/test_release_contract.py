"""The release contract: schema sanity, the mini fixture, and that the validator catches breakage."""
import copy
import os

import pandas as pd
import pytest

from bor.release_schema import MANIFEST_REQUIRED, REASON_CODES, STAGES, TABLES, TOP_LEVEL_REASONS
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
    assert {top for top, _ in REASON_CODES.values()} <= set(TOP_LEVEL_REASONS)
    assert set(TOP_LEVEL_REASONS) == {top for top, _ in REASON_CODES.values()}   # all four are used


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
    """N1 and N3 are grouped though no A-C pair was ever scored: the witness path runs 1-2 (a base
    decision) then 2-3 (a feedback merge), both on cluster K1."""
    t, _ = _load()
    w = t["group_witness"].sort_values("step")
    assert list(zip(w["node_a"], w["node_b"], w["stage"])) == [   # read_release leaves strings
        ("1", "2", "identity.splink_base"), ("2", "3", "identity.splink_feedback")]
    ev = t["decision_events"]
    on_k1 = ev[ev["cluster_id"] == "K1"]
    assert set(on_k1["stage"]) == {"identity.splink_base", "identity.splink_feedback"}
    # no event scores an A-C pair
    assert not ((ev["subject_id"] == "ident-a") & (ev["counterpart_id"] == "ident-c")).any()
    # the feedback merge cites the shared company's exact contacts, with no names
    sup = t["decision_support"]
    assert set(sup.loc[sup["decision_id"] == "d2", "support_id"]) == {"101:10103:0", "103:10303:0"}


def test_fixture_explains_an_absence():
    t, _ = _load()
    s = t["bbl_status"].set_index("bbl").loc["3000010004"]
    assert s["status"] == "not_in_group" and s["top_level_reason"] == "no_qualifying_linkage"
    d3 = t["decision_events"].set_index("decision_id").loc["d3"]
    assert d3["outcome"] == "rejected" and float(d3["score"]) < float(d3["threshold"])


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
    extra["step"], extra["node_a"], extra["node_b"] = 3, 1, 3
    extra["assertion_key"] = "mini-0001/owner_portfolio/OG-1/w3"
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
    t["groups"].loc[0, "building_count"] = "9"
    assert ("groups", "counts") in _checks(t)


def test_node_in_two_groups_is_a_key_violation():
    t, _ = _load()
    dup = t["group_members"].iloc[[0]].copy()
    dup["group_id"] = "OG-9"
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
    full, clusters = resolved
    tables, _ = build_mapping(pg, full, clusters)
    assert {n for n in tables} <= {n for n, t in TABLES.items() if t.status == "implemented"}
    assert _errors(tables) == []
