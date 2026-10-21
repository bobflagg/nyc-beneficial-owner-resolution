"""nlr's trace -> release tables, on a small synthetic run (no database)."""
import json

import pandas as pd

from bor import identity_events as ie
from bor.release_validate import validate_release

NLR, BOR = "nlr-test", "bor-test"


def _identities(rows):
    return pd.DataFrame(rows, columns=["unique_id", "sources"])


def _run():
    """u1-u2 are linked by a scored pair; u3 joins them through a shared company (a feedback merge);
    u4 is vetoed from u3; u5 is common-name vetoed from u4 and its address is masked; u9 was removed
    by a curated list."""
    ident = _identities([("u1", ["3000010001:1:101"]), ("u2", ["3000010002:2:201"]),
                         ("u3", ["3000010003:3:301"]), ("u4", ["3000010004:4:401"]),
                         ("u5", ["3000010005:5:501"])])
    excluded = _identities([("u9", ["3000010009:9:901"])])
    clusters = pd.DataFrame({"unique_id": ["u1", "u2", "u3", "u4", "u5"],
                             "cluster_id": ["u3", "u3", "u3", "u4", "u5"]})
    base = pd.DataFrame({"unique_id": ["u1", "u2", "u3", "u4", "u5"],
                         "cluster_id": ["u2", "u2", "u3", "u4", "u5"]})
    trace = {
        "pairs": pd.DataFrame([
            ("u1", "u2", 0.9995, 2, "accepted", None, 3, True),
            ("u4", "u3", 0.9996, 0, "rejected", "first_name_veto", 2, True),
            ("u5", "u4", 0.9997, 3, "rejected", "common_name_veto", 200, False)],
            columns=["unique_id_l", "unique_id_r", "match_probability", "gamma_first_name", "outcome",
                     "reason", "name_rarity", "same_address"]),
        "address_masked": pd.DataFrame({"unique_id": ["u5"], "addr_degree": [40]}),
        "feedback": pd.DataFrame([
            ("u2", "u3", "accepted", None, ["ACME"]),
            ("u4", "u5", "rejected", "degree_unknown", ["ORPHAN"])],
            columns=["base_cluster_l", "base_cluster_r", "outcome", "reason", "shared_corps"]),
        "feedback_sources": pd.DataFrame([
            ("u2", "u3", "ACME", "3000010001", 1, 150), ("u2", "u3", "ACME", "3000010003", 3, 350),
            ("u4", "u5", "ORPHAN", "3000010004", 4, 450)],
            columns=["base_cluster_l", "base_cluster_r", "corp", "bbl", "registrationid", "registrationcontactid"]),
    }
    keys = pd.DataFrame([(r, c, 0) for r, c in [(1, 101), (2, 201), (3, 301), (4, 401), (5, 501), (9, 901),
                                                 (1, 150), (3, 350), (4, 450)]],
                        columns=["registrationid", "registrationcontactid", "k"])
    return ident, excluded, clusters, base, trace, keys


def _tables():
    ident, excluded, clusters, base, trace, keys = _run()
    imap = ie.identity_ids(ident, excluded)
    cmap, bmap = ie.cluster_ids(clusters, "C"), ie.cluster_ids(base, "BC")
    events, support = ie.decision_tables(trace, excluded, clusters, base, 0.999, imap, cmap, bmap, keys, NLR, BOR)
    return dict(
        events=events, support=support, imap=imap, cmap=cmap, bmap=bmap,
        ident_obs=ie.identity_observations(ident, excluded, imap, keys, {"3000010001"}),
        ident_cl=ie.identity_clusters(clusters, base, imap, cmap, bmap), keys=keys)


def test_each_nlr_record_becomes_the_right_event():
    t = _tables()
    e = t["events"].set_index(["stage", "outcome", "reason_code"], drop=False)
    assert len(e) == 7
    acc = t["events"][(t["events"]["stage"] == "identity.splink_base") & (t["events"]["outcome"] == "accepted")].iloc[0]
    assert (acc["rule"], acc["score"], acc["threshold"], acc["cluster_id"]) == ("splink_model", 0.9995, 0.999, "C0000001")
    veto = t["events"][t["events"]["reason_code"] == "first_name_veto"].iloc[0]
    assert (veto["outcome"], veto["rule"]) == ("rejected", "first_name_veto")
    assert veto["score"] > veto["threshold"] and pd.isna(veto["cluster_id"])   # a gate overruled the score
    common = t["events"][t["events"]["reason_code"] == "common_name_veto"].iloc[0]
    assert json.loads(common["detail"]) == {"name_rarity": 200, "same_address": False}
    masked = t["events"][t["events"]["outcome"] == "masked"].iloc[0]
    assert (masked["reason_code"], masked["rule"]) == ("address_evidence_masked", "splink_address_evidence_mask")
    assert json.loads(masked["detail"]) == {"addr_degree": 40}
    cur = t["events"][t["events"]["stage"] == "identity.curated"].iloc[0]
    assert (cur["outcome"], cur["reason_code"], cur["rule_version"]) == ("excluded", "curated_exclusion", BOR)


def test_feedback_events_join_base_clusters_and_have_no_pair_score():
    t = _tables()
    fb = t["events"][t["events"]["stage"] == "identity.splink_feedback"].set_index("outcome")
    acc, rej = fb.loc["accepted"], fb.loc["rejected"]
    assert (acc["subject_type"], acc["counterpart_type"]) == ("base_cluster", "base_cluster")
    assert pd.isna(acc["score"]) and acc["cluster_id"] == "C0000001" and acc["rule"] == "shared_company_feedback"
    assert (rej["reason_code"], rej["rule"]) == ("shared_company_degree_unknown", "shared_company_guard")
    assert json.loads(acc["detail"]) == {"n_shared_corporations": 1}      # no corporation names leave
    # the base clusters are the pre-feedback ones: {u1,u2} and {u3}
    assert {acc["subject_id"], acc["counterpart_id"]} == {t["bmap"]["u2"], t["bmap"]["u3"]}


def test_feedback_support_cites_the_contacts_carrying_the_corporation():
    t = _tables()
    fb_acc = t["events"][(t["events"]["stage"] == "identity.splink_feedback")
                         & (t["events"]["outcome"] == "accepted")].iloc[0]["decision_id"]
    sup = t["support"]
    assert set(sup.loc[sup["decision_id"] == fb_acc, "support_id"]) == {"1:150:0", "3:350:0"}
    assert (sup["role"] == "shared_company").all() and (sup["support_type"] == "observation").all()


def test_identity_observations_include_excluded_identities_and_flag_tied_registrations():
    t = _tables()
    io = t["ident_obs"]
    assert set(io["identity_id"]) == set(t["imap"].values())              # u9 is there too
    assert "I0000006" == t["imap"]["u9"] and t["imap"]["u9"] not in set(t["ident_cl"]["identity_id"])
    tied = io.set_index("bbl")["tied_registration"]
    assert tied["3000010001"] and not tied["3000010002"]


def test_an_ambiguous_contact_pair_is_attached_to_every_content():
    ident = _identities([("u1", ["3000010001:1:101"])])
    keys = pd.DataFrame([(1, 101, 0), (1, 101, 1)], columns=["registrationid", "registrationcontactid", "k"])
    io = ie.identity_observations(ident, ident.iloc[0:0], {"u1": "I0000001"}, keys, set())
    assert sorted(io["observation_id"]) == ["1:101:0", "1:101:1"]


def test_ids_and_decision_numbers_do_not_depend_on_splinks_labels():
    ident, excluded, clusters, base, trace, keys = _run()
    relabel = {"u3": "ZZ3", "u4": "ZZ4", "u5": "ZZ5"}      # same partition, other roots
    clusters2 = clusters.assign(cluster_id=clusters["cluster_id"].map(lambda c: relabel.get(c, c)))
    assert ie.cluster_ids(clusters, "C") != ie.cluster_ids(clusters2, "C")        # labels differ
    a, b = ie.cluster_ids(clusters, "C"), ie.cluster_ids(clusters2, "C")
    assert [a[k] for k in ("u3", "u4", "u5")] == [b[k] for k in ("ZZ3", "ZZ4", "ZZ5")]


def test_the_assembled_identity_layer_satisfies_the_contract():
    t = _tables()
    ids = pd.concat([t["ident_obs"]["observation_id"], t["support"]["support_id"]]).drop_duplicates()
    parts = ids.str.split(":", expand=True).astype(int)
    obs = pd.DataFrame({"observation_id": ids.to_numpy(), "registration_id": parts[0].to_numpy(),
                        "registration_contact_id": parts[1].to_numpy(), "k": parts[2].to_numpy(), "pair_variants": 1})
    tables = {"observations": obs, "identity_clusters": t["ident_cl"], "identity_observations": t["ident_obs"],
              "decision_events": t["events"], "decision_support": t["support"]}
    errors = [v for v in validate_release(tables, check_manifest_too=False) if v.severity == "error"]
    assert errors == []


# --- the reference dump (needs the database; ~1.5 min for the fit) -----------------------------

def test_identity_layer_on_the_reference_dump(pg, resolved):
    from bor.lineage import build_mapping
    tables, rep = build_mapping(pg, resolved)
    by = rep["decision_events_by_outcome"]
    TOL = 30
    # nlr's trace volumes measured for docs/w2-design.md
    assert abs(by["identity.splink_base/accepted"] - 19_838) <= TOL
    ev = tables["decision_events"]
    base_rej = ev[(ev["stage"] == "identity.splink_base") & (ev["outcome"] == "rejected")]
    assert abs(int((base_rej["reason_code"] == "first_name_veto").sum()) - 1_682) <= TOL
    assert abs(int((base_rej["reason_code"] == "common_name_veto").sum()) - 903) <= TOL
    assert abs(by["identity.splink_base/masked"] - 5_298) <= TOL
    assert by["identity.curated/excluded"] == 24                       # the curated list is deterministic
    assert abs(by["identity.splink_feedback/accepted"] - 1_197) <= TOL
    # every identity nlr resolved is traceable to an HPD contact
    assert rep["identity_bbl_pairs_without_observation"] == 0
    # an accepted decision always sits on a cluster, a rejected one never does
    acc = ev["outcome"] == "accepted"
    assert ev.loc[acc, "cluster_id"].notna().all() and ev.loc[~acc, "cluster_id"].isna().all()


def test_croman_offices_are_joined_by_a_feedback_merge_not_by_any_pair_score(pg, resolved):
    """The acceptance scenario of docs/w2-design.md: two offices become one cluster only through a
    shared company, and no event scores them against each other."""
    from bor.lineage import build_mapping
    tables, _ = build_mapping(pg, resolved)
    fb = resolved.trace["feedback"]
    hit = fb[(fb["outcome"] == "accepted")
             & fb["shared_corps"].map(lambda cs: any("CENTENNIAL" in c for c in cs))]
    assert len(hit), "expected Croman's offices to be bridged through Centennial Properties"
    row = hit.iloc[0]
    bmap = ie.cluster_ids(resolved.base_clusters, "BC")
    left, right = bmap[row.base_cluster_l], bmap[row.base_cluster_r]
    ev, ic = tables["decision_events"], tables["identity_clusters"]

    merge = ev[(ev["stage"] == "identity.splink_feedback") & (ev["outcome"] == "accepted")
               & (ev["subject_id"].isin([left, right])) & (ev["counterpart_id"].isin([left, right]))]
    assert len(merge) == 1 and pd.isna(merge.iloc[0]["score"])
    sup = tables["decision_support"]
    assert (sup["decision_id"] == merge.iloc[0]["decision_id"]).sum() >= 2    # the company's contacts

    # the two offices end up in one final cluster...
    final = ic.groupby("base_cluster_id")["cluster_id"].first()
    assert final[left] == final[right]
    # ...yet no accepted pair decision crosses between them
    side = ic.set_index("identity_id")["base_cluster_id"]
    pairs = ev[(ev["stage"] == "identity.splink_base") & (ev["outcome"] == "accepted")]
    crossing = pairs[[{side[a], side[b]} == {left, right} for a, b in zip(pairs["subject_id"], pairs["counterpart_id"])]]
    assert crossing.empty
