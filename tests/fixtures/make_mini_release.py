"""Regenerate tests/fixtures/mini_release (synthetic; not real data).

    uv run python tests/fixtures/make_mini_release.py

Seven lots. Lots 1, 2, 3 and 5 form group OP-1: 1-2 by a scored base decision, 2-3 by a
feedback merge (1 and 3 were never compared), 3-5 by a base decision, and lot 5 is a co-op left
out of the rental footprint. Lot 4 is blocked from lot 3's identity by the first-name veto. Lots 6
and 7 link, but the group is dropped as co-op/condo dominated.
"""
import csv
import hashlib
import json
import os

D = os.path.join(os.path.dirname(__file__), "mini_release")
os.makedirs(D, exist_ok=True)
R = "mini-0001"
B = [f"30000100{n:02d}" for n in range(1, 8)]
I = [f"I{n:07d}" for n in range(1, 8)]          # identities a..g
C = {"abce": "C0000001", "d": "C0000002", "fg": "C0000003"}
BC = {"ab": "BC0000001", "ce": "BC0000002", "d": "BC0000003", "fg": "BC0000004"}
OBS = [f"10{n}:10{n}05:0" for n in range(1, 8)]  # the person contact behind each lot
CORP = ["101:10103:0", "103:10303:0"]            # one private company on lots 1 and 3
OG1 = f"{R}/owner_portfolio/OP-1"


def w(name, header, rows):
    with open(f"{D}/{name}.csv", "w", newline="") as f:
        x = csv.writer(f)
        x.writerow(header)
        x.writerows(rows)


w("observations", ["observation_id", "registration_id", "registration_contact_id", "k", "pair_variants"],
  sorted([[o, o.split(":")[0], o.split(":")[1], 0, 1] for o in OBS + CORP]))
w("node_observations", ["node_id", "bbl", "registration_id", "n_candidates", "selected_observation_id", "ambiguous"],
  [[n, B[n - 1], 100 + n, 1, OBS[n - 1], "False"] for n in range(1, 8)])
clusters = {1: "abce", 2: "abce", 3: "abce", 4: "d", 5: "abce", 6: "fg", 7: "fg"}
base = {1: "ab", 2: "ab", 3: "ce", 4: "d", 5: "ce", 6: "fg", 7: "fg"}
w("identity_clusters", ["identity_id", "cluster_id", "base_cluster_id"],
  [[I[n - 1], C[clusters[n]], BC[base[n]]] for n in range(1, 8)])
w("identity_observations", ["identity_id", "bbl", "observation_id", "tied_registration"],
  [[I[n - 1], B[n - 1], OBS[n - 1], "False"] for n in range(1, 8)])
w("node_identity_matches", ["node_id", "identity_id", "bbl"], [[n, I[n - 1], B[n - 1]] for n in range(1, 8)])
w("node_cluster", ["node_id", "cluster_id", "n_clusters", "tied"],
  [[n, C[clusters[n]], 1, "False"] for n in range(1, 8)])

EV = ["decision_id", "layer", "stage", "subject_type", "subject_id", "counterpart_type", "counterpart_id",
      "outcome", "reason_code", "rule", "rule_version", "score", "threshold", "cluster_id", "detail"]
w("decision_events", EV, [
    ["d1", "identity", "identity.splink_base", "identity", I[0], "identity", I[1], "accepted", "", "splink_model", "fixture-0", 0.9995, 0.999, C["abce"], ""],
    ["d2", "identity", "identity.splink_feedback", "base_cluster", BC["ab"], "base_cluster", BC["ce"], "accepted", "", "shared_company_feedback", "fixture-0", "", "", C["abce"], "shared private company; degree cap passed"],
    ["d3", "identity", "identity.splink_base", "identity", I[3], "identity", I[2], "rejected", "first_name_veto", "first_name_veto", "fixture-0", 0.9996, 0.999, "", "scored above threshold; blocked by the gate"],
    ["d4", "identity", "identity.splink_base", "identity", I[2], "identity", I[4], "accepted", "", "splink_model", "fixture-0", 0.9997, 0.999, C["abce"], ""],
    ["d5", "owner_portfolio", "owner_portfolio.footprint", "bbl", B[4], "", "", "excluded", "coop_condo_excluded", "coop_condo_contact_rule", "fixture-0", "", "", "", "co-op lot in a surviving group"],
    ["d6", "identity", "identity.splink_base", "identity", I[5], "identity", I[6], "accepted", "", "splink_model", "fixture-0", 0.9993, 0.999, C["fg"], ""],
    ["d7", "owner_portfolio", "owner_portfolio.footprint", "group", "OP-6", "", "", "dropped", "coop_condo_dominated", "group_footprint_rule", "fixture-0", "", "", "", "rental lots are fewer than half the footprint"],
    ["d8", "owner_portfolio", "owner_portfolio.footprint", "bbl", B[5], "", "", "excluded", "coop_condo_dominated", "group_footprint_rule", "fixture-0", "", "", "", ""],
    ["d9", "owner_portfolio", "owner_portfolio.footprint", "bbl", B[6], "", "", "excluded", "coop_condo_dominated", "group_footprint_rule", "fixture-0", "", "", "", ""],
])
w("decision_support", ["decision_id", "support_type", "support_id", "role"], [
    ["d1", "observation", OBS[0], "endpoint_a"], ["d1", "observation", OBS[1], "endpoint_b"],
    ["d2", "observation", CORP[0], "bridging_company"], ["d2", "observation", CORP[1], "bridging_company"],
    ["d3", "observation", OBS[3], "endpoint_a"], ["d3", "observation", OBS[2], "endpoint_b"],
    ["d4", "observation", OBS[2], "endpoint_a"], ["d4", "observation", OBS[4], "endpoint_b"],
    ["d6", "observation", OBS[5], "endpoint_a"], ["d6", "observation", OBS[6], "endpoint_b"],
    ["d5", "bbl", B[4], "excluded_lot"],
])
w("groups", ["layer", "group_id", "assertion_key", "composition", "split", "lot_count", "total_lot_count", "witness_pieces"],
  [["owner_portfolio", "OP-1", OG1, "identity", "", 3, 4, 1]])
w("group_members", ["layer", "group_id", "node_id", "assertion_key"],
  [["owner_portfolio", "OP-1", n, f"{OG1}/n{n}"] for n in (1, 2, 3, 5)])
w("group_bbls", ["layer", "group_id", "bbl", "rental"],
  [["owner_portfolio", "OP-1", B[n - 1], "False" if n == 5 else "True"] for n in (1, 2, 3, 5)])
w("group_witness", ["layer", "group_id", "step", "node_a", "node_b", "stage", "basis_type", "basis_id", "assertion_key"], [
    ["owner_portfolio", "OP-1", 1, 1, 2, "identity.splink_base", "identity_cluster", C["abce"], f"{OG1}/w1"],
    ["owner_portfolio", "OP-1", 2, 2, 3, "identity.splink_feedback", "identity_cluster", C["abce"], f"{OG1}/w2"],
    ["owner_portfolio", "OP-1", 3, 3, 5, "identity.splink_base", "identity_cluster", C["abce"], f"{OG1}/w3"]])
w("bbl_status", ["layer", "bbl", "status", "group_id", "reason_code", "top_level_reason"], [
    ["owner_portfolio", B[0], "in_group", "OP-1", "", ""], ["owner_portfolio", B[1], "in_group", "OP-1", "", ""],
    ["owner_portfolio", B[2], "in_group", "OP-1", "", ""],
    ["owner_portfolio", B[3], "not_in_group", "", "first_name_veto", "below_eligibility_rule"],
    ["owner_portfolio", B[4], "excluded_from_footprint", "OP-1", "coop_condo_excluded", "excluded_by_policy"],
    ["owner_portfolio", B[5], "not_in_group", "", "coop_condo_dominated", "excluded_by_policy"],
    ["owner_portfolio", B[6], "not_in_group", "", "coop_condo_dominated", "excluded_by_policy"]])
w("method_metrics", ["stage", "metric", "unit", "population", "n", "numerator", "denominator", "precision", "ci_lower",
                     "ci_upper", "confidence_level", "interval_method", "estimator", "strata_ref", "eval_artifact",
                     "eval_version", "adjudication_status", "provisional", "note"],
  [[st, "precision", "pair", "", "", "", "", "", "", "", "", "", "", "", "", "", "none", "True", "fixture: unevaluated"]
   for st in ("identity.splink_base", "identity.splink_feedback")])

files = sorted(f for f in os.listdir(D) if f.endswith(".csv"))
manifest = {
    "schema_version": "0.1.0", "run_id": R, "snapshot_id": "fixture-2026-10-20", "effective_date": "2026-10-20",
    "bor_revision": "fixture", "nlr_revision": "fixture", "source_tree_hash": "fixture",
    "dependency_lock_digest": "fixture", "threshold": 0.999, "parameters": {"splink_threshold": 0.999},
    "pluto_snapshot_id": "fixture-pluto",
    "source_tables": {t: {"row_count": 0, "fingerprint": "fixture", "fingerprint_method": "fixture"}
                      for t in ("hpd_contacts", "hpd_registrations", "wow_landlords", "real_property_master", "pluto_latest")},
    "deed_selection_rule": {"rule": "doctype ILIKE '%DEED%'", "version": "fixture"},
    "normalizer_versions": {"business_address": "fixture", "owner_name": "fixture"},
    "artifacts": {"group_witness": "representative", "observations": "complete", "decision_events": "complete"},
    "stage_vocabulary_version": "0.1.0", "reason_vocabulary_version": "0.1.0",
    "output_checksums": {f: hashlib.sha256(open(f"{D}/{f}", "rb").read()).hexdigest() for f in files},
    "note": "Synthetic fixture for the release contract. Not real data.",
}
json.dump(manifest, open(f"{D}/manifest.json", "w"), indent=2)
print(len(files), "tables")
