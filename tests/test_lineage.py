"""Mapping tables: unit tests on synthetic frames (no database), then a regression run against
the reference dump (skipped without PG* env; see conftest)."""
import numpy as np
import pandas as pd

from bor.lineage import (DIGEST_SQL, build_mapping, node_cluster_tables,
                         node_observation_tables, observation_id)
from bor.splink_bridge import select_cluster


# --- observation ids ---------------------------------------------------------------------------

def test_observation_id_format():
    assert observation_id(357997, 35799705, 0) == "357997:35799705:0"
    assert observation_id(1.0, 2.0, 1.0) == "1:2:1"      # read_sql can hand back floats


def test_digest_is_positional_and_treats_null_like_empty():
    assert "concat_ws('|'" in DIGEST_SQL and DIGEST_SQL.count("coalesce(") == 11


# --- node -> contact ---------------------------------------------------------------------------

def _cand(rows):
    return pd.DataFrame(rows, columns=["nodeid", "bbl", "registrationid", "registrationcontactid", "k"])


def test_unique_contact_is_selected():
    no, alt = node_observation_tables(_cand([(1, "3000010001", 10, 105, 0)]))
    r = no.iloc[0]
    assert r.selected_observation_id == "10:105:0" and r.n_candidates == 1 and not r.ambiguous
    assert alt.empty


def test_tied_contacts_are_ambiguous_and_listed():
    no, alt = node_observation_tables(_cand([
        (2, "3000010002", 11, 203, 0), (2, "3000010002", 11, 204, 0)]))
    r = no.iloc[0]
    assert r.ambiguous and r.n_candidates == 2 and pd.isna(r.selected_observation_id)
    assert sorted(alt["observation_id"]) == ["11:203:0", "11:204:0"]


def test_same_contact_id_with_differing_content_is_two_candidates():
    no, _ = node_observation_tables(_cand([
        (3, "3000010003", 12, 305, 0), (3, "3000010003", 12, 305, 1)]))
    assert no.iloc[0].n_candidates == 2 and no.iloc[0].ambiguous


def test_row_without_a_qualifying_contact_is_kept_with_zero_candidates():
    no, alt = node_observation_tables(_cand([(4, "3000010004", 13, np.nan, np.nan)]))
    r = no.iloc[0]
    assert r.n_candidates == 0 and not r.ambiguous and pd.isna(r.selected_observation_id)
    assert alt.empty


def test_each_node_bbl_row_appears_once():
    no, _ = node_observation_tables(_cand([
        (1, "a", 10, 105, 0), (1, "b", 10, 105, 0), (2, "c", 11, 203, 0), (2, "c", 11, 204, 0)]))
    assert len(no) == 3 and not no.duplicated(["node_id", "bbl"]).any()


# --- node -> cluster ---------------------------------------------------------------------------

def _votes(rows):
    return pd.DataFrame(rows, columns=["nodeid", "cluster_id"])


def test_single_cluster_node():
    nc, alt = node_cluster_tables(_votes([(1, "c9"), (1, "c9")]))
    r = nc.iloc[0]
    assert r.cluster_id == "c9" and r.n_clusters == 1 and not r.tied and alt.empty


def test_plurality_wins_without_a_tie():
    nc, alt = node_cluster_tables(_votes([(1, "b"), (1, "a"), (1, "a")]))
    assert nc.iloc[0].cluster_id == "a" and nc.iloc[0].n_clusters == 2 and not nc.iloc[0].tied
    assert dict(zip(alt["cluster_id"], alt["selected"])) == {"a": True, "b": False}


def test_tie_goes_to_the_smallest_label_and_is_flagged():
    nc, alt = node_cluster_tables(_votes([(1, "b"), (1, "a")]))
    assert nc.iloc[0].cluster_id == "a" and nc.iloc[0].tied
    assert len(alt) == 2


def test_select_cluster_matches_the_original_mode_rule():
    v = _votes([(1, 7), (1, 3), (1, 7), (2, 5), (2, 4)])
    got = dict(zip(*[select_cluster(v)[c] for c in ("nodeid", "cluster_id")]))
    assert got == {1: 7, 2: 4}             # most common; tie -> smallest


# --- regression against the reference dump ----------------------------------------------------

def test_mapping_against_reference_dump(pg, resolved):
    full, clusters = resolved
    tables, rep = build_mapping(pg, full, clusters)

    # exact, from the data: one wow_landlords row per BBL, one node per BBL
    assert rep["node_bbl_rows"] == 171_347
    assert not tables["node_observations"].duplicated(["node_id", "bbl"]).any()
    assert rep["node_bbls_without_candidate"] == 0
    assert rep["node_bbls_ambiguous_contact"] == 642

    # every (identity, bbl) nlr resolved is traceable to an HPD contact
    assert rep["identity_bbl_pairs_without_observation"] == 0

    # Splink-dependent: tolerant (docs/w0-findings.md measured 113 / 751 / 639)
    assert abs(rep["nodes_unmatched"] - 113) <= 30
    assert abs(rep["nodes_straddling_2plus_clusters"] - 751) <= 60
    assert 0.7 <= rep["straddling_nodes_tied"] / rep["nodes_straddling_2plus_clusters"] <= 0.95

    # every referenced observation is defined
    obs = set(tables["observations"]["observation_id"])
    assert set(tables["identity_observations"]["observation_id"]) <= obs
    assert set(tables["node_observations"]["selected_observation_id"].dropna()) <= obs
