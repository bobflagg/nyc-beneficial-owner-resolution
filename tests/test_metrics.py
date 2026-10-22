"""bor.metrics: method_metrics transcribed from the evaluation, nothing estimated."""
import copy
import json

import pandas as pd
import pytest

from bor.eval.score import wilson
from bor.metrics import LINK_STAGES, load_evaluation, method_metrics_table
from bor.release_schema import ADJUDICATION_STATUSES, METRIC_SCOPES, STAGES, TABLES
from bor.release_validate import validate_release


def _stratum(n, adjudicable, counts):
    out = {"n": n, "adjudicable": adjudicable, "coverage": round(adjudicable / n, 3), "counts": counts}
    if "c1" in counts:
        c1, c2, d = counts["c1"], counts["c2"], counts["different"]
        out["strict_precision"], out["inclusive_precision"] = wilson(c1, c1 + d), wilson(c1 + c2, c1 + c2 + d)
        out["c2_share"] = 0.0
    else:
        out["split_precision"] = wilson(counts["good"], counts["adjudicable"])
    return out


EVAL = {"sha256": "ab" * 32,
        "frame": {"frame": "f", "builder_commit": "c0ffee", "built_at": "2026-01-01",
                  "strata": {"S1a_deed_held": {"frame": 40, "n": 10}, "S1b_deed_linked_successor": {"frame": 6, "n": 6},
                             "S2_model": {"frame": 100, "n": 10}, "S3_aggregator": {"frame": 30, "n": 10},
                             "S4_hard_neg": {"frame": 50, "n": 10}}},
        "metrics": {"strata": {
            "S1a_deed_held": _stratum(10, 10, dict(c1=8, c2=1, different=1)),
            "S1b_deed_linked_successor": _stratum(6, 5, dict(c1=3, c2=0, different=2)),
            "S2_model": _stratum(10, 10, dict(c1=9, c2=0, different=1)),
            "S3_aggregator": _stratum(10, 10, dict(good=9, adjudicable=10)),
            "S4_hard_neg": _stratum(10, 8, dict(good=6, adjudicable=8))}}}


@pytest.fixture(scope="module")
def table():
    return method_metrics_table(EVAL, "human_llm_provisional").set_index(["stage", "metric"])


def test_the_table_has_the_contract_columns_and_a_row_per_stratum_and_per_unevaluated_stage(table):
    flat = table.reset_index()
    assert list(flat.columns) == [c.name for c in TABLES["method_metrics"].columns]
    # three evaluated stages x (strict, inclusive), two split strata, six unevaluated stages x (strict, inclusive)
    assert len(flat) == 3 * 2 + 2 + 6 * 2
    assert set(flat["stage"]) == set(LINK_STAGES) | set(METRIC_SCOPES)
    assert flat["stage"].isin(STAGES + METRIC_SCOPES).all()


def test_estimates_are_transcribed_not_recomputed(table):
    r = table.loc[("identity.splink_base", "precision_strict")]
    assert (r["numerator"], r["denominator"], r["n"]) == (9, 10, 10)
    assert (r["precision"], r["ci_lower"], r["ci_upper"]) == wilson(9, 10)
    # strict leaves the C2 pair out entirely; inclusive counts it
    s, i = table.loc[("deed.held_since", "precision_strict")], table.loc[("deed.held_since", "precision_inclusive")]
    assert (s["numerator"], s["denominator"]) == (8, 9) and (i["numerator"], i["denominator"]) == (9, 10)
    sp = table.loc[("method.hard_negatives", "split_precision")]
    assert (sp["numerator"], sp["denominator"], sp["unit"]) == (6, 8, "pair")


def test_a_census_is_marked_and_a_sample_is_not(table):
    assert "census" not in table.loc[("deed.held_since", "precision_strict"), "interval_method"]
    census = method_metrics_table({**EVAL, "frame": {**EVAL["frame"], "strata": {
        **EVAL["frame"]["strata"], "S1b_deed_linked_successor": {"frame": 6, "n": 6}}}}).set_index(["stage", "metric"])
    assert "census" in census.loc[("deed.linked_successor", "precision_strict"), "interval_method"]
    assert all("Wilson" in x for x in table["interval_method"].dropna())


def test_each_row_says_where_its_evidence_comes_from(table):
    r = table.loc[("deed.linked_successor", "precision_strict")]
    assert r["eval_artifact"] == "bor.eval.score metrics.json sha256:" + "ab" * 8
    assert r["eval_version"] == "f@c0ffee built 2026-01-01" and r["strata_ref"].startswith("f:S1b_deed_linked_successor")
    assert r["confidence_level"] == 0.95 and "frame 6" in r["population"]


def test_unevaluated_stages_say_why_and_the_pooling_in_the_identity_sample_is_stated(table):
    for stage in ("identity.splink_feedback", "identity.curated", "identity.registered_llc", "network.identity",
                  "network.name", "network.address"):
        for metric in ("precision_strict", "precision_inclusive"):
            r = table.loc[(stage, metric)]
            assert pd.isna(r["precision"]) and pd.isna(r["numerator"]) and r["note"], (stage, metric)
            assert r["adjudication_status"] == "none" and r["provisional"]
    assert "pools" in table.loc[("identity.splink_feedback", "precision_strict"), "note"]
    assert "pools" not in table.loc[("identity.splink_base", "precision_strict"), "note"] or \
        "shared-company" in table.loc[("identity.splink_base", "precision_strict"), "population"]
    assert "different question" in table.loc[("network.name", "precision_strict"), "note"]


def test_the_status_of_the_gold_is_stated_and_only_a_blind_human_gold_is_final():
    for status, final in (("human_llm_provisional", False), ("synthetic", False), ("blind_human", True)):
        t = method_metrics_table(EVAL, status)
        evaluated = t[t["precision"].notna()]
        assert (evaluated["adjudication_status"] == status).all() and evaluated["provisional"].eq(not final).all()
    note = method_metrics_table(EVAL, "human_llm_provisional").query("stage == 'deed.held_since'").iloc[0]["note"]
    assert "LLM second reader" in note and "blind human re-adjudication is pending" in note
    with pytest.raises(ValueError, match="gold_status"):
        method_metrics_table(EVAL, "blind human")


def test_without_an_evaluation_every_link_stage_still_has_a_row():
    t = method_metrics_table(None)
    assert set(t["stage"]) == set(LINK_STAGES) and t["precision"].isna().all() and t["note"].notna().all()
    assert set(t["adjudication_status"]) == {"none"}


def test_old_scorer_output_without_counts_is_refused_with_the_fix():
    old = copy.deepcopy(EVAL)
    del old["metrics"]["strata"]["S2_model"]["counts"]
    with pytest.raises(ValueError, match="rerun"):
        method_metrics_table(old, "human_llm_provisional")
    with pytest.raises(ValueError, match="unknown stratum"):
        method_metrics_table({**EVAL, "metrics": {"strata": {"S9": EVAL["metrics"]["strata"]["S2_model"]}}})


def test_load_evaluation_hashes_the_file_it_read(tmp_path):
    (tmp_path / "metrics.json").write_text(json.dumps(EVAL["metrics"]))
    (tmp_path / "frame_manifest.json").write_text(json.dumps(EVAL["frame"]))
    ev = load_evaluation(tmp_path)
    assert len(ev["sha256"]) == 64 and ev["frame"]["frame"] == "f"
    assert method_metrics_table(ev, "synthetic")["eval_artifact"].dropna().str.contains(ev["sha256"][:16]).all()


def test_explain_shows_the_published_estimate_beside_the_weak_stage_and_only_when_there_is_one():
    import os

    from bor import explain as ex
    fx = os.path.join(os.path.dirname(__file__), "fixtures")
    syn, mini = ex.Release.from_dir(os.path.join(fx, "synthetic_release")), ex.Release.from_dir(os.path.join(fx, "mini_release"))
    weak = ex.explain_pair(syn, "9000200001", "9000200003").weakest[0]
    assert "published strict precision 0.50 (95% interval 0.19 to 0.81; 3 of 6 sampled pairs; provisional" in weak
    assert "not the chance this link is right" in weak
    assert "published" not in ex.explain_pair(mini, "3000010001", "3000010003").weakest[0]      # unevaluated: nothing to show


# --- the validator's view of the table ---------------------------------------------------------------------------

def _errors(df, witness_stages=()):
    T = {"method_metrics": df}
    if witness_stages:
        T["group_witness"] = pd.DataFrame({"layer": "owner_portfolio", "group_id": "OP-1", "step": range(len(witness_stages)),
                                           "node_a": "1", "node_b": "2", "stage": list(witness_stages),
                                           "basis_type": "x", "basis_id": "x", "assertion_key": [f"r/{i}" for i in range(len(witness_stages))]})
    return {(v.table, v.check) for v in validate_release(T, None, check_manifest_too=False) if v.severity == "error"
            and v.table == "method_metrics"}


def _typed(df):
    return df.astype(object).where(df.notna(), None).astype(str).where(df.notna(), None)


def test_a_published_table_passes_the_validator():
    assert _errors(_typed(method_metrics_table(EVAL, "human_llm_provisional"))) == set()


def test_the_validator_catches_counts_that_disagree_with_the_estimate():
    t = _typed(method_metrics_table(EVAL, "human_llm_provisional"))
    i = t.index[(t["stage"] == "identity.splink_base") & (t["metric"] == "precision_strict")][0]
    t.loc[i, "numerator"] = "5"
    assert ("method_metrics", "counts") in _errors(t)


def test_the_validator_catches_a_split_precision_on_a_stage_and_the_reverse():
    t = _typed(method_metrics_table(EVAL, "human_llm_provisional"))
    i = t.index[t["metric"] == "split_precision"][0]
    t.loc[i, "stage"] = "deed.held_since"
    assert ("method_metrics", "scope") in _errors(t)
    t = _typed(method_metrics_table(EVAL, "human_llm_provisional"))
    j = t.index[t["metric"] == "precision_strict"][0]
    t.loc[j, "stage"] = "method.hard_negatives"
    assert ("method_metrics", "scope") in _errors(t)


def test_the_validator_wants_a_row_for_every_stage_a_path_cites():
    t = _typed(method_metrics_table(None))
    assert _errors(t, ["identity.splink_base", "deed.held_since"]) == set()
    assert ("method_metrics", "coverage") in _errors(t[t["stage"] != "deed.held_since"], ["deed.held_since"])


def test_metric_names_and_gold_statuses_are_controlled():
    t = _typed(method_metrics_table(None))
    bad = t.copy()
    bad.loc[0, "metric"] = "precision"
    assert ("method_metrics", "enum") in _errors(bad)
    bad = t.copy()
    bad.loc[0, "adjudication_status"] = "blind"
    assert ("method_metrics", "enum") in _errors(bad)
    assert set(ADJUDICATION_STATUSES) >= {"none", "synthetic", "human_llm_provisional", "blind_human"}


# --- the scorer's counts, and a real build (need the reference Postgres) -------------------------------------------------

def test_the_scorer_records_the_counts_behind_each_proportion_and_who_annotated(pg, tmp_path):
    from bor.eval.score import score

    def pair(pid, stratum, signal, watchline):
        return {"pair_id": pid, "stratum": stratum, "signal": signal, "watchline": watchline,
                "a_bbls": ["1000010001"], "b_bbls": ["1000010002"]}

    key = [pair("p1", "S2_model", "splink-fellegi-sunter", "SAME"), pair("p2", "S2_model", "splink-fellegi-sunter", "SAME"),
           pair("p3", "S1a_deed_held", "acris-deed", "SAME"), pair("p4", "S3_aggregator", "aggregator-mask", "DIFFERENT"),
           pair("p5", "S3_aggregator", "aggregator-mask", "DIFFERENT")]
    labels = {"p1": "SAME", "p2": "DIFFERENT", "p3": "SAME", "p4": "DIFFERENT", "p5": "INDETERMINATE"}
    ann = [{"pair_id": p, "annotator_id": "h1", "label": lab, "evidence_tiers": ["T1", "T2"]} for p, lab in labels.items()]
    ann.append({"pair_id": "p3", "annotator_id": "adjudicator", "label": "SAME", "evidence_tiers": ["T1"]})
    (tmp_path / "key.jsonl").write_text("\n".join(map(json.dumps, key)))
    (tmp_path / "ann.jsonl").write_text("\n".join(map(json.dumps, ann)))
    rep = score(str(tmp_path / "key.jsonl"), str(tmp_path / "ann.jsonl"), tmp_path / "out")
    assert rep["strata"]["S2_model"]["counts"] == {"c1": 1, "c2": 0, "different": 1}
    assert rep["strata"]["S1a_deed_held"]["counts"] == {"c1": 0, "c2": 1, "different": 0}   # same-source only: C2
    assert rep["strata"]["S3_aggregator"]["counts"] == {"good": 1, "adjudicable": 1}      # indeterminate left out
    assert rep["gold"] == {"annotators": ["adjudicator", "h1"], "adjudicator_rows": 1}
    # the counts reproduce the published proportions
    c = rep["strata"]["S2_model"]["counts"]
    assert rep["strata"]["S2_model"]["strict_precision"] == wilson(c["c1"], c["c1"] + c["different"])


def test_a_built_release_publishes_a_row_for_every_stage_its_paths_cite(release_build):
    out, result = release_build
    t = pd.read_csv(out / "method_metrics.csv", dtype=str)
    w = pd.read_csv(out / "group_witness.csv", dtype=str)
    assert set(w["stage"]) <= set(t["stage"]) and t["precision"].isna().all() and t["note"].notna().all()
    assert [v for v in result["violations"] if v.severity == "error"] == []
    assert result["manifest"]["diagnostics"]["evaluation"] is None
