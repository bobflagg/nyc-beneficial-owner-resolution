"""The name tables against the reference Postgres (skipped without PG*). The facts used are about companies and
a street address, so no individual's name is in the repository."""
import pandas as pd

from bor import names
from bor.lineage import _PAIR_VARIANTS_SQL

CITADEL_DEED = "2008072300342001"          # 15 lots, $58.4M, to Citadel Estates LLC


def test_a_deed_has_its_parties_and_consideration(pg):
    docs, parties = names.deed_tables(pg, [CITADEL_DEED])
    assert len(docs) == 1 and docs.iloc[0]["doc_type"] == "DEED" and docs.iloc[0]["doc_amount"] > 5e7
    assert list(parties.loc[parties["party_type"] == "grantee", "name"]) == ["CITADEL ESTATES LLC"]
    assert (parties["party_type"] == "grantor").sum() == 15
    assert list(parties.loc[parties["party_type"] == "grantor", "party_index"]) == list(range(15))


def test_a_lot_has_its_pluto_address(pg):
    out = names.lot_addresses(pg, ["3012590047", "9999999999"])
    assert out["bbl"].tolist() == ["3012590047"] and out.iloc[0]["address"] == "377 EASTERN PARKWAY"


def test_a_contact_that_hpd_repeats_with_differing_content_has_a_row_per_variant(pg):
    v = pd.read_sql(_PAIR_VARIANTS_SQL, pg).sort_values(["registrationid", "registrationcontactid"]).iloc[0]
    n = int(v["pair_variants"])
    obs = pd.DataFrame({"observation_id": [f"{v['registrationid']}:{v['registrationcontactid']}:{k}" for k in range(n)],
                        "registration_id": int(v["registrationid"]), "registration_contact_id": int(v["registrationcontactid"]),
                        "k": range(n)})
    out = names.observation_contacts(pg, obs)
    assert len(out) == n and out["observation_id"].tolist() == obs["observation_id"].tolist()
    assert len(out.drop(columns="observation_id").drop_duplicates()) == n          # the variants really differ


def test_the_built_release_names_everything_it_cites(release_build):
    from bor.release_validate import read_release, validate_release
    out, result = release_build
    tables, manifest = read_release(str(out))
    assert manifest["schema_version"] == "0.2.0"
    assert {"observation_contacts", "identity_names", "node_names", "deed_documents", "deed_parties",
            "lot_addresses"} <= set(tables)
    assert [v for v in result["violations"] if v.severity == "error"] == []
    assert not [v for v in validate_release(tables, manifest, path=str(out)) if v.check == "names_cover" and v.severity == "error"]
    rep = manifest["diagnostics"]["names"]
    assert rep["observations_without_contact"] == 0 and rep["documents_described"] == rep["documents_cited"]
